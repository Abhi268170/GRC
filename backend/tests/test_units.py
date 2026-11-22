"""Pure functions: no database, no network."""

import io
import zipfile

import pytest

from app.core.config import Settings
from app.core.security import hash_password, verify_password, verify_password_async
from app.core.uploads import clean_filename, content_disposition
from app.services import ai, documents, jobs
from app.services.question_gen import ControlContext, DomainScope, Req

BASE = dict(database_url="postgresql+asyncpg://u:pw-long-enough@h/db", s3_access_key="k", s3_secret_key="a-real-secret",
            jwt_secret="x" * 40, super_admin_email="a@b.co", super_admin_password="a-long-password", ai_service_token="t" * 30)


def test_production_refuses_placeholder_secrets():
    Settings(**BASE, environment="production")  # fine
    for override, expected in (({"jwt_secret": "change-me-to-a-long-random-string"}, "JWT_SECRET"),
                               ({"super_admin_password": "change-me"}, "SUPER_ADMIN_PASSWORD"),
                               ({"ai_service_token": ""}, "AI_SERVICE_TOKEN")):
        with pytest.raises(ValueError, match=expected):
            Settings(**{**BASE, **override}, environment="production")
        assert Settings(**{**BASE, **override}, environment="development").unsafe_settings()  # only warned about


def test_environment_must_be_a_known_name():
    with pytest.raises(ValueError):
        Settings(**BASE, environment="prod")


async def test_password_check_for_an_unknown_account_is_false_but_still_does_the_work():
    hashed = hash_password("secret-password")
    assert verify_password("secret-password", hashed) and not verify_password("other", hashed)
    assert await verify_password_async("secret-password", hashed)
    assert not await verify_password_async("secret-password", None)


@pytest.mark.parametrize(("given", "expected"), [
    ("report.pdf", "report.pdf"), ("../../etc/passwd", "passwd"), ("C:\\Users\\me\\a.docx", "a.docx"),
    ("na\x00me\r\n.txt", "name.txt"), ("", "file"), (None, "file"), ("...", "file"),
])
def test_clean_filename(given, expected):
    assert clean_filename(given) == expected


def test_content_disposition_is_safe_for_any_name():
    header = content_disposition('Política "final" – 政策.pdf')
    header.encode("latin-1")  # would raise if the header couldn't be sent
    assert header.startswith('attachment; filename="') and '"final"' not in header
    assert "filename*=UTF-8''Pol%C3%ADtica%20%22final%22" in header
    assert content_disposition("a.pdf", inline=True).startswith("inline;")


def test_looks_like_checks_the_first_bytes():
    assert documents.looks_like(b"%PDF-1.7 ...", documents.PDF)
    assert not documents.looks_like(b"<html>", documents.PDF)
    assert documents.looks_like(b"\x89PNG\r\n\x1a\n....", "image/png")
    assert not documents.looks_like(b"MZ\x90\x00", documents.DOCX)
    assert documents.looks_like(b"plain text", "text/plain") and not documents.looks_like(b"bin\x00ary", "text/csv")


def _zip(members: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return out.getvalue()


def test_office_files_that_unpack_too_large_are_refused(monkeypatch):
    monkeypatch.setattr(documents, "MAX_UNZIPPED_BYTES", 1000)
    documents.check_archive(_zip({"a.xml": b"x" * 500}))
    bomb = _zip({"a.xml": b"0" * 100_000})
    assert len(bomb) < 1000  # small on the wire, large once unpacked
    with pytest.raises(documents.FileTooLarge):
        documents.check_archive(bomb)
    with pytest.raises(documents.FileTooLarge):
        documents.docx_text(bomb)
    with pytest.raises(documents.FileTooLarge):
        documents.check_archive(b"not a zip at all")


def test_only_ai_messages_are_shown_to_users():
    assert jobs.safe_message(ai.AIError("The AI declined to process this request")) == "The AI declined to process this request"
    leaky = RuntimeError('duplicate key value violates unique constraint "uq_run_rollup" DETAIL: Key (run_id)=(...)')
    assert jobs.safe_message(leaky) == jobs.GENERIC_FAILURE


def test_scope_groups_requirements_under_their_control():
    import uuid

    c1, c2 = uuid.uuid4(), uuid.uuid4()
    reqs = [Req(uuid.uuid4(), "R1", "A one", "s1", "g", ["e"], True, c1), Req(uuid.uuid4(), "R2", "A one", "s2", "", [], None, c1),
            Req(uuid.uuid4(), "R3", "B two", "s3", "", [], False, c2)]
    scope = DomainScope(uuid.uuid4(), "Identity", None, reqs, {c1: ControlContext(label="A one", area="Gov")})
    groups = scope.by_control()
    assert [(ctx.label, [r.key for r in rs]) for ctx, rs in groups] == [("A one", ["R1", "R2"]), ("B two", ["R3"])]
    assert [[r.key for r in rs] for _, rs in scope.by_control(keep=lambda r: r.key != "R1")] == [["R2"], ["R3"]]
    contract = scope.contract()
    assert contract.controls[0].context.area == "Gov" and contract.controls[0].requirements[0].mandatory is True
    assert contract.controls[1].context.label == "B two"  # a control without stored context still gets its label

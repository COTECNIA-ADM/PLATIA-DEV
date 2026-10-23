from app.extensions import db
from app.models import AuditLog, User

from conftest import PASSWORD


def test_create_admin_asks_password_and_validates_it(seeded):
    runner = seeded.test_cli_runner()
    weak = runner.invoke(args=["create-admin", "--email", "a@example.com", "--name", "A"], input="corta\ncorta\n")
    assert weak.exit_code != 0
    ok = runner.invoke(args=["create-admin", "--email", "A@example.com", "--name", "A"],
                       input=f"{PASSWORD}\n{PASSWORD}\n")
    assert ok.exit_code == 0, ok.output
    assert PASSWORD not in ok.output
    user = db.session.scalar(db.select(User).filter_by(email="a@example.com"))
    assert user.is_superadmin and user.password_hash != PASSWORD


def test_reset_mfa_is_audited(seeded, make_user):
    user = make_user()
    user.mfa_enabled, user.mfa_secret_encrypted = True, "x"
    db.session.commit()
    result = seeded.test_cli_runner().invoke(args=["reset-mfa", "--email", user.email])
    assert result.exit_code == 0
    db.session.refresh(user)
    assert user.mfa_enabled is False
    assert db.session.scalar(db.select(AuditLog).filter_by(action="MFA_DISABLED")).severity == "CRITICAL"

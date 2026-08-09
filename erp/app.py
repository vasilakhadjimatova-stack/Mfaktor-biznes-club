"""
Mfaktor ERP — asosiy kirish nuqtasi.

1-bosqich: O'quv bo'limi (kurslar, guruhlar, davomat, AI baholash,
risk-nazorat, sertifikat). Keyingi bosqichlar: Moliya ko'prigi, CRM,
AI-mentor, rol-play simulyator.
"""
import logging
import os
import re

from flask import Flask, redirect, url_for

from config import Config
from database import init_db
from core.auth import current_user

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    init_db(app)

    from core.security import init_security
    init_security(app)

    from modules.auth.routes import bp as auth_bp
    from modules.education.routes import bp as education_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(education_bp)

    @app.context_processor
    def inject_globals():
        return {
            "current_user": current_user(),
            "company_name": Config.COMPANY_NAME,
            "company_tagline": Config.COMPANY_TAGLINE,
        }

    # ── Pul formati: 45 640 000 → "45.6 mln so'm" ──
    @app.template_filter("som")
    def _fmt_som(v):
        try:
            v = float(v or 0)
        except (TypeError, ValueError):
            return "0 so'm"
        a = abs(v)
        if a >= 1_000_000_000:
            s = f"{v/1e9:.1f} mlrd"
        elif a >= 1_000_000:
            s = f"{v/1e6:.1f} mln"
        elif a >= 1_000:
            s = f"{v/1e3:.0f} ming"
        else:
            return f"{v:,.0f}".replace(",", " ") + " so'm"
        return s.replace(".0 ", " ") + " so'm"

    # ── Sana: "2026-08-09" → "09.08.2026" ──
    _ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

    @app.template_filter("dmy")
    def _fmt_dmy(v):
        s = str(v or "").strip()
        if not s:
            return ""
        m = _ISO_DATE.match(s)
        if not m:
            return s
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}{s[m.end():]}"

    @app.route("/")
    def root():
        if current_user():
            return redirect(url_for("education.index"))
        return redirect(url_for("auth.login"))

    @app.route("/healthz")
    def healthz():
        from flask import jsonify
        from sqlalchemy import text
        from database import db
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify({"status": "ok"}), 200
        except Exception:
            db.session.rollback()
            return jsonify({"status": "degraded"}), 503

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5070))
    debug = (os.environ.get("FLASK_DEBUG", "0") == "1") \
        and not Config.IS_PRODUCTION
    logging.info(f"🎓 Mfaktor ERP — http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)

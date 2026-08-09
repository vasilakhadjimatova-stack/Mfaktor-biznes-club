"""
Foydalanuvchi — xodimlar, 6 xonali kod bilan kirish.

Ruxsat modeli: perm — JSON list ("education", "finance", ...) yoki "all".
"""
import json
from datetime import datetime

from database import db

# Modullar (ruxsat birliklari) — yangi bo'lim qo'shilganda shu yerga yoziladi
MODULES = ["education", "finance", "crm", "admin"]

DEPARTMENTS = ["Boshqaruv", "O'quv bo'limi", "Sotuv", "Moliya", "Marketing"]


class User(db.Model):
    __tablename__ = "users"

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False)
    position   = db.Column(db.String(120), nullable=False, default="")
    code       = db.Column(db.String(12), nullable=False, unique=True)
    department = db.Column(db.String(40), nullable=False, default="Boshqaruv")
    _perm      = db.Column("perm", db.Text, nullable=False, default="[]")
    is_admin   = db.Column(db.Boolean, nullable=False, default=False)
    is_active  = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def perm(self):
        if self._perm == "all":
            return "all"
        try:
            return json.loads(self._perm)
        except (ValueError, TypeError):
            return []

    @perm.setter
    def perm(self, value):
        self._perm = "all" if value == "all" else json.dumps(
            value, ensure_ascii=False)

    def can(self, module: str) -> bool:
        if self.is_admin or self.perm == "all":
            return True
        return module in self.perm

    @property
    def is_boss(self) -> bool:
        return bool(self.is_admin or "rahbar" in (self.position or "").lower())

    def __repr__(self):
        return f"<User {self.name}>"

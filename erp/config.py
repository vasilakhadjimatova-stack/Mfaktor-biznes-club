"""Mfaktor ERP — konfiguratsiya."""
import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-mfaktor-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///mfaktor_erp.db").replace(
        "postgres://", "postgresql://")   # Railway eski URL formati uchun
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    COMPANY_NAME = "Mfaktor Biznes Maktabi"
    COMPANY_TAGLINE = "O'zbekistonda №1 texnologik biznes-maktab"
    IS_PRODUCTION = bool(os.environ.get("RAILWAY_ENVIRONMENT")
                         or os.environ.get("PRODUCTION"))

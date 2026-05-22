from flask import Flask
from flask_cors import CORS

from app.config import get_config
from app.extensions import bcrypt, celery, db, init_celery, jwt, limiter, migrate


def create_app(config_class=None):
    app = Flask(__name__)

    # ── Config ──────────────────────────────────────────────────────────────────
    if config_class is None:
        config_class = get_config()
    app.config.from_object(config_class)

    # ── Extensions ──────────────────────────────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    bcrypt.init_app(app)
    limiter.init_app(app)
    init_celery(app, celery)

    # ── CORS ────────────────────────────────────────────────────────────────────
    CORS(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=True,
    )

    # ── Models — imported so db.metadata is populated before Alembic runs ───────
    _import_models()

    # ── JWT error handlers ───────────────────────────────────────────────────────
    _register_jwt_handlers(jwt)

    # ── CLI commands ─────────────────────────────────────────────────────────────
    from app.commands import (
        seed_db_command, nse_group,
        verify_user_command, create_dev_user_command,
        seed_scan_snapshot_command, inspect_snapshots_command,
    )
    app.cli.add_command(seed_db_command)
    app.cli.add_command(nse_group)
    app.cli.add_command(verify_user_command)
    app.cli.add_command(create_dev_user_command)
    app.cli.add_command(seed_scan_snapshot_command)
    app.cli.add_command(inspect_snapshots_command)

    # ── Blueprints ───────────────────────────────────────────────────────────────
    _register_blueprints(app)

    return app


def _import_models():
    from app.models import (  # noqa: F401  — imports populate db.metadata for Alembic
        OtpVerification,
        NseStock,
        NseUniverse,
        NseUniverseStock,
        Payment,
        Plan,
        PlanToolMap,
        RefreshToken,
        Role,
        ScanJob,
        ScanResult,
        ScannerNotification,
        Subscription,
        Tool,
        User,
        UserTrackedSymbol,
        UserAlertSettings,
        MaxPainSnapshot,
        OIWallSnapshot,
        RegimeSnapshot,
        ScanSnapshot,
    )


def _register_blueprints(app: Flask):
    from app.api.health import health_bp
    app.register_blueprint(health_bp, url_prefix="/api")

    from app.api.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix="/api/auth")

    from app.api.plans import plans_bp
    app.register_blueprint(plans_bp, url_prefix="/api/plans")

    from app.api.tools import tools_bp
    app.register_blueprint(tools_bp, url_prefix="/api/tools")

    from app.api.subscriptions import subscriptions_bp
    app.register_blueprint(subscriptions_bp, url_prefix="/api/subscriptions")

    from app.api.payments import payments_bp
    app.register_blueprint(payments_bp, url_prefix="/api/payments")

    from app.api.scanners import scanners_bp
    app.register_blueprint(scanners_bp, url_prefix="/api/scanners")

    from app.api.market_data import market_data_bp
    app.register_blueprint(market_data_bp, url_prefix="/api/market-data")

    from app.api.scans import scans_bp
    app.register_blueprint(scans_bp, url_prefix="/api/scans")

    from app.api.notifications import notifications_bp
    app.register_blueprint(notifications_bp, url_prefix="/api/notifications")

    from app.api.watchlist import watchlist_bp
    app.register_blueprint(watchlist_bp, url_prefix="/api/watchlist")

    from app.api.alert_settings import alert_settings_bp
    app.register_blueprint(alert_settings_bp, url_prefix="/api/alert-settings")

    from app.api.broker import broker_bp
    app.register_blueprint(broker_bp)

    from app.api.options.routes import options_bp
    app.register_blueprint(options_bp)

    from app.api.max_pain.routes import max_pain_bp
    app.register_blueprint(max_pain_bp)

    from app.api.max_pain.history_routes import history_bp
    app.register_blueprint(history_bp)

    from app.api.max_pain.validation_routes import validation_bp
    app.register_blueprint(validation_bp)

    from app.api.max_pain.regime_routes import regime_bp
    app.register_blueprint(regime_bp)

    from app.api.max_pain.trade_routes import trade_bp
    app.register_blueprint(trade_bp)

    from app.api.max_pain.portfolio_routes import portfolio_bp
    app.register_blueprint(portfolio_bp)

    from app.api.max_pain.monte_carlo_routes import monte_carlo_bp
    app.register_blueprint(monte_carlo_bp)

    from app.api.max_pain.research_routes import research_bp
    app.register_blueprint(research_bp)

    from app.api.max_pain.walkforward_routes import walkforward_bp
    app.register_blueprint(walkforward_bp)


def _register_jwt_handlers(jwt_manager):
    from app.utils.response import error

    @jwt_manager.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return error("Token has expired.", 401, error_code="TOKEN_EXPIRED")

    @jwt_manager.invalid_token_loader
    def invalid_token_callback(reason):
        return error(f"Invalid token: {reason}", 401, error_code="TOKEN_INVALID")

    @jwt_manager.unauthorized_loader
    def missing_token_callback(reason):
        return error("Authorization token is required.", 401, error_code="TOKEN_MISSING")

    @jwt_manager.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        return error("Token has been revoked.", 401, error_code="TOKEN_REVOKED")

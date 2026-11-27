"""Logging configuration with structured logging."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pythonjsonlogger import jsonlogger


def init_logging(app):
    """Initialize structured logging for the application."""

    # Remove default Flask logger handlers
    app.logger.handlers = []

    # Set log level based on environment
    if app.config.get("DEBUG"):
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    # JSON formatter for structured logging
    json_formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s %(pathname)s %(lineno)d'
    )

    # Console handler with JSON format
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(json_formatter)

    # File handler with rotation
    file_handler = RotatingFileHandler(
        'logs/abroad.log',
        maxBytes=10485760,  # 10MB
        backupCount=10
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(json_formatter)

    # Error file handler
    error_handler = RotatingFileHandler(
        'logs/abroad-errors.log',
        maxBytes=10485760,
        backupCount=10
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(json_formatter)

    # Add handlers to app logger
    app.logger.addHandler(console_handler)
    app.logger.addHandler(file_handler)
    app.logger.addHandler(error_handler)
    app.logger.setLevel(log_level)

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)

    # Suppress noisy loggers
    logging.getLogger('werkzeug').setLevel(logging.WARNING)

    app.logger.info(
        "Logging initialized",
        extra={
            "environment": app.config.get("ENV"),
            "debug": app.config.get("DEBUG"),
        }
    )


def log_request_context(app):
    """Add request context to logs."""
    from flask import request, g

    @app.before_request
    def log_request_info():
        user = g.get("user")
        app.logger.info(
            "Request received",
            extra={
                "method": request.method,
                "path": request.path,
                "ip": request.remote_addr,
                "user_id": user["id"] if user else None,
                "user_agent": request.user_agent.string,
            }
        )

    @app.after_request
    def log_response_info(response):
        app.logger.info(
            "Response sent",
            extra={
                "status_code": response.status_code,
                "path": request.path,
            }
        )
        return response

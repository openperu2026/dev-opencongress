from flask import Flask
from app.routes.landing import landing_bp
from app.routes.bills import bills_bp
from app.routes.congress import congress_bp
# from app.routes import landing_bp, bills_bp, congress_bp, info_bp


def create_app():
    app = Flask(__name__)

    app.register_blueprint(landing_bp)
    app.register_blueprint(bills_bp)
    app.register_blueprint(congress_bp)
    # app.register_blueprint(info_bp)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)

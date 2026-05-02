from flask import Blueprint, render_template

landing_bp = Blueprint("landing", __name__, template_folder="../templates")


@landing_bp.route("/")
def index():
    """
    Landing page (main menu)
    """
    menu_items = [
        {"name": "Bills", "url": "/bills"},  # considering using url_for
        {"name": "Congress Members", "url": "/congress"},
        {"name": "Data", "url": "/info"},
    ]

    return render_template("landing/index.html", menu_items=menu_items)

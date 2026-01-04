#devices_route.py
from flask import Blueprint, render_template
from apps.tools.auth import permission_required

bp_devices = Blueprint('devices', __name__, url_prefix='/devices')

@bp_devices.route('/dashboard')
@permission_required('SA','GA','HA','HP','DA','DH','SE','ST')
def devices():
    return render_template("devices/dashboard.html")


@bp_devices.route('/dashboard_index')
@permission_required('SA','GA','HA','HP','DA','DH','SE','ST')
def dashboard_index():
    return render_template("devices/dashboard_index.html")


from . import devices_list
from . import devices_form
from . import devices_events
from . import devices_events_card
from . import devices_logs
from . import devices_check_in
from . import devices_labels


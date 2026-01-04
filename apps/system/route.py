#system_route.py
from flask import Blueprint, render_template
from apps.tools.auth import login_required, permission_required


bp_system = Blueprint('system', __name__, url_prefix='/system')

@bp_system.route('/dashboard')

@permission_required('SA','DA')
def system():
    return render_template("system/dashboard.html")



from . import system_index
from . import hospital_manger
from . import department_manger
from . import user_manger
from . import device_mac
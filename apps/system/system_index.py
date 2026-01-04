# system_index.py 系统管理首页
from flask import  render_template
from .route import bp_system 
from apps.tools.auth import login_required, permission_required




@bp_system.route('/dashboard_index')
@permission_required('SA','GA','HA','HP','DA','DH')
def system_index():
    return render_template("system/dashboard_index.html")
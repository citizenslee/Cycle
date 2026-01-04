# 主启动文件
from flask import Flask,g
from flask_wtf.csrf import CSRFProtect
from datetime import timedelta
import os
# 导入注册蓝图
from apps.index.index import bp_index
from apps.tools.login import bp_login
from apps.system.route import bp_system
from apps.orders.route import bp_orders
from apps.devices.route import bp_devices
from apps.materials.materials import bp_materials
from apps.vendor.route import bp_vendor
from apps.tools.photo_view import bp_photo_view
from apps.schedule.route import bp_schedule
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


app = Flask(__name__)
#注册首页相关路由
app.register_blueprint(bp_index)
#注册系统板块相关蓝图
app.register_blueprint(bp_system)
#注册系统板块相关蓝图
app.register_blueprint(bp_orders)
#注册设备板块相关蓝图
app.register_blueprint(bp_devices)
#注册物资板块相关蓝图
app.register_blueprint(bp_materials)
app.register_blueprint(bp_login)
app.register_blueprint(bp_vendor)
app.register_blueprint(bp_photo_view)
app.register_blueprint(bp_schedule)
#
print(app.url_map)

# ------- Session 配置（24 小时过期） -------
app.config["SECRET_KEY"] = "Li9991QCDCGRE1*啊"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=24)
app.config["WTF_CSRF_CHECK_DEFAULT"] = False 
csrf = CSRFProtect(app)



# 注册关闭数据库连接的回调函数
@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=80, debug=True)


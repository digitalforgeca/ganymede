import sys

class Web:
    dashboard_instance = None

sys.modules['web'] = Web()

def set_dashboard():
    import web
    web.dashboard_instance = "HELLO"

def get_dashboard():
    from web import dashboard_instance
    print(dashboard_instance)

get_dashboard()
set_dashboard()
get_dashboard()

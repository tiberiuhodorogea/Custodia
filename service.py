"""
Windows Service wrapper for the Backup Service.

Install:   python service.py install
Start:     python service.py start
Stop:      python service.py stop
Remove:    python service.py remove

The service runs the FastAPI/uvicorn server on 0.0.0.0:8550.
"""

import logging
import logging.handlers
import os
import sys

# Ensure the project directory is on sys.path so imports work when
# running as a Windows service (working dir may differ).
SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

import win32serviceutil  # noqa: E402
import win32service      # noqa: E402
import win32event        # noqa: E402
import servicemanager    # noqa: E402

LOG_DIR  = os.path.join(SERVICE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "service.log")


def _setup_logging():
    """Configure a rotating file logger shared by the service and the app."""
    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    if root.handlers:
        return  # already configured

    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,   # 5 MB per file
        backupCount=3,               # keep 3 rotated files -> 20 MB max
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Silence loggers that would flood the file with routine noise
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


log = logging.getLogger(__name__)


class BackupService(win32serviceutil.ServiceFramework):
    _svc_name_ = "BackupService"
    _svc_display_name_ = "Backup Service"
    _svc_description_ = (
        "Automatic file backup service with web dashboard. "
        "Access at http://<hostname>:8550"
    )

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.server = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self.server:
            self.server.should_exit = True
        log.info("Service stop requested")

    def SvcDoRun(self):
        _setup_logging()
        log.info("Service starting")
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        try:
            self.main()
            log.info("Service stopped cleanly")
        except Exception:
            log.exception("Service crashed - unhandled exception in main()")
            raise

    def main(self):
        os.chdir(SERVICE_DIR)

        import asyncio
        import contextlib
        import uvicorn
        from main import app  # noqa: F811

        # Windows Service SvcDoRun() runs in a non-main thread, which hits two
        # restrictions:
        # 1. ProactorEventLoop.__init__ calls set_wakeup_fd() - main thread only.
        #    Fix: use SelectorEventLoop policy instead.
        # 2. uvicorn.Server.capture_signals calls signal.signal() - main thread only.
        #    Fix: replace capture_signals with a no-op context manager on the instance.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        config = uvicorn.Config(app, host="0.0.0.0", port=8550, log_level="info", log_config=None)
        self.server = uvicorn.Server(config)
        self.server.capture_signals = contextlib.nullcontext

        log.info("Web server starting on 0.0.0.0:8550")
        self.server.run()
        log.info("Web server stopped")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Called without args - SCM is starting the service
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(BackupService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(BackupService)

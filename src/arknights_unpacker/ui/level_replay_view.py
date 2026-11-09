"""Run the local 3D player inside the level preview window."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from shiboken6 import delete


class _PreviewRequests(QWebEngineUrlRequestInterceptor):
    def __init__(self, url, parent):
        super().__init__(parent)
        self.port = url.port()
        self.prefix = url.path().rsplit('/', 1)[0] + '/'
        self.blob_origin = f'blob:http://127.0.0.1:{self.port}/'

    def interceptRequest(self, info):
        url = info.requestUrl()
        # GLTFLoader exposes embedded textures as same-origin blob URLs.
        local = (url.scheme() == 'http' and url.host() == '127.0.0.1'
                 and url.port() == self.port and url.path().startswith(self.prefix))
        embedded = url.scheme() == 'data' or url.toString().startswith(self.blob_origin)
        if not (local or embedded):
            info.block(True)


class _ReplayPage(QWebEnginePage):
    def __init__(self, profile, url, parent):
        super().__init__(profile, parent)
        self._replay_url = url

    def acceptNavigationRequest(self, url, _kind, main_frame):
        return main_frame and url == self._replay_url

    def createWindow(self, _kind):
        return None


class LevelReplayView(QWebEngineView):
    def __init__(self, url, parent):
        super().__init__(parent)
        self.setObjectName('levelReplayView')
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._url = QUrl(url)
        self._profile = QWebEngineProfile(self)
        self._requests = _PreviewRequests(self._url, self._profile)
        self._profile.setUrlRequestInterceptor(self._requests)
        self._page = _ReplayPage(self._profile, self._url, self)
        self._page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        self.setPage(self._page)
        self._fullscreen_presentation = False
        self.loadFinished.connect(self._apply_presentation)

    def load_replay(self):
        self.load(self._url)

    def set_fullscreen_presentation(self, enabled):
        self._fullscreen_presentation = enabled
        self._apply_presentation()

    def toggle_playback(self):
        if self._page is not None:
            self._page.runJavaScript("document.querySelector('#play')?.click()")

    def _apply_presentation(self):
        if self._page is not None:
            enabled = 'true' if self._fullscreen_presentation else 'false'
            self._page.runJavaScript(f"document.documentElement.classList.toggle('replay-fullscreen', {enabled})")

    def shutdown(self):
        if self._page is not None:
            self.stop()
            # The WebEngine profile must outlive its page.
            delete(self._page)
            self._page = None

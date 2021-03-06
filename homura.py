from __future__ import print_function, absolute_import
import datetime
import os
import six
import sys
import time
import pycurl
from requests.utils import unquote as _unquote
from humanize import naturalsize

PY3 = sys.version_info[0] == 3
STREAM = sys.stderr

if PY3:
    from urllib.parse import urlparse
else:
    from urlparse import urlparse


def eval_path(path):
    return os.path.abspath(os.path.expanduser(path))


def unquote(s):
    res = s
    if not PY3:
        if isinstance(res, six.text_type):
            res = s.encode('utf-8')
    return _unquote(res)


def dict_to_list(d):
    return ['%s: %s' % (k, v) for k, v in d.iteritems()]


class Homura(object):
    """Donwload manager that displays progress"""
    progress_template = \
        '%(percent)6d%% %(downloaded)12s %(speed)15s %(eta)18s ETA'
    eta_limit = 2592000  # 30 days

    def __init__(self, url, path=None, headers=None, session=None,
                 show_progress=True, resume=True, auto_retry=True):
        """
        :param str url: URL of the file to be downloaded
        :param str path: local path for the downloaded file; if None, it will
            be the URL base name
        :param dict headers: extra headers
        :param session: session used to download (if you want to work with
            requests library)
        :type session: `class:requests.Session`
        :param bool show_progress: whether to show download progress
        :param bool resume: whether to resume download (by
            filename)
        :param bool auto_retry: whether to retry automatically upon closed
            transfer until the file's download is finished
        """
        self.url = url
        self.path = self._get_path(path)
        self.headers = headers
        self.session = session
        self.show_progress = show_progress
        self.resume = resume
        self.auto_retry = auto_retry
        self.start_time = None
        self.content_length = 0
        self.downloaded = 0
        self._cookie_header = self._get_cookie_header()
        self._last_time = 0.0

    def __del__(self):
        self.done()

    def _get_cookie_header(self):
        if self.session is not None:
            cookie = dict(self.session.cookies)
            res = []
            for k, v in cookie.items():
                s = '%s=%s' % (k, v)
                res.append(s)
            if not res:
                return None
            return '; '.join(res)

    def _get_path(self, path=None):
        if path is None:
            o = urlparse(self.url)
            path = os.path.basename(o.path)
            return unquote(path)
        else:
            return eval_path(path)

    def _get_pycurl_headers(self):
        headers = self.headers or {}
        if self._cookie_header is not None:
            headers['Cookie'] = self._cookie_header
        return dict_to_list(headers) or None

    def curl(self):
        """Sending cURL request to download"""
        c = pycurl.Curl()
        # Resume download
        if os.path.exists(self.path) and self.resume:
            mode = 'ab'
            self.downloaded = os.path.getsize(self.path)
            c.setopt(pycurl.RESUME_FROM, self.downloaded)
        else:
            mode = 'wb'
        with open(self.path, mode) as f:
            c.setopt(c.URL, self.url)
            c.setopt(c.WRITEDATA, f)
            h = self._get_pycurl_headers()
            if h is not None:
                c.setopt(pycurl.HTTPHEADER, h)
            c.setopt(c.NOPROGRESS, 0)
            c.setopt(c.PROGRESSFUNCTION, self.progress)
            c.perform()

    def start(self):
        """Start downloading"""
        if not self.auto_retry:
            self.curl()
            return
        while not self.is_finished:
            try:
                self.curl()
            except pycurl.error as e:
                # transfer closed with n bytes remaining to read
                if e.args[0] == 18:
                    pass
                # HTTP server doesn't seem to support byte ranges.
                # Cannot resume.
                elif e.args[0] == 33:
                    break
                else:
                    raise e

    def progress(self, download_t, download_d, upload_t, upload_d):
        if int(download_t) == 0:
            return
        if self.content_length == 0:
            self.content_length = self.downloaded + int(download_t)
        if not self.show_progress:
            return
        if self.start_time is None:
            self.start_time = time.time()
        duration = time.time() - self.start_time + 1
        speed = download_d / duration
        speed_s = naturalsize(speed, binary=True)
        speed_s += '/s'
        eta = int((download_t - download_d) / speed)
        if eta < self.eta_limit:
            eta_s = str(datetime.timedelta(seconds=eta))
        else:
            eta_s = 'n/a'
        downloaded = self.downloaded + download_d
        downloaded_s = naturalsize(downloaded, binary=True)
        percent = int(downloaded / (self.content_length) * 100)
        params = {
            'downloaded': downloaded_s,
            'percent': percent,
            'speed': speed_s,
            'eta': eta_s,
        }
        if STREAM.isatty():
            p = (self.progress_template + '\r') % params
        else:
            current_time = time.time()
            if self._last_time == 0.0:
                self._last_time = current_time
            else:
                interval = current_time - self._last_time
                if interval < 0.5:
                    return
                self._last_time = current_time
            p = (self.progress_template + '\n') % params
        STREAM.write(p)
        STREAM.flush()

    @property
    def is_finished(self):
        if os.path.exists(self.path):
            return self.content_length == os.path.getsize(self.path)

    def done(self):
        STREAM.write('\n')
        STREAM.flush()


def download(url, path=None, headers=None, session=None, show_progress=True,
             resume=True, auto_retry=True):
    """Download using download manager"""
    hm = Homura(url, path, headers, session, show_progress, resume, auto_retry)
    hm.start()

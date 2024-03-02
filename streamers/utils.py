
from urllib.parse import urlparse,urlunparse,urlencode

import flask

def construct_url(path: str, scheme: str = 'http', **qargs):
    (_, netloc, _, _, _, _) = urlparse(flask.request.url_root)
    query_params = urlencode(qargs)
    return urlunparse((scheme,netloc, path, _, query_params, _))

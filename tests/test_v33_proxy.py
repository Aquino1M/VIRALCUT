from app.services import proxy_media

def test_proxy_geometry_uses_480p_long_edge():
    assert proxy_media.proxy_geometry('9:16') == (270,480)
    assert proxy_media.proxy_geometry('16:9') == (854,480)
    assert proxy_media.proxy_geometry('1:1') == (480,480)
    assert proxy_media.proxy_geometry('4:5') == (384,480)

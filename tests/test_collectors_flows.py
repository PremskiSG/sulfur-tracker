from sulfur_tracker.collectors import comtrade_flows as cf


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def test_fetch_flows_dedupes_modes_and_drops_world(monkeypatch):
    payload = {"data": [
        {"partnerCode": 784, "motCode": 0, "customsCode": "C00", "partner2Code": 0,
         "netWgt": 110_000_000},
        {"partnerCode": 784, "motCode": 2100, "customsCode": "C00", "partner2Code": 0,
         "netWgt": 110_000_000},                                    # mode dup -> ignored
        {"partnerCode": 682, "motCode": 0, "customsCode": "C00", "partner2Code": 0,
         "netWgt": 95_400_000},
        {"partnerCode": 0, "motCode": 0, "customsCode": "C00", "partner2Code": 0,
         "netWgt": 374_200_000},                                    # World row -> dropped
    ]}
    monkeypatch.setattr(cf, "http_get", lambda *a, **k: _FakeResp(payload))
    flows = cf.fetch_flows(360, "M", "202603")
    assert flows == {784: 110.0, 682: 95.4}
    assert 0 not in flows


def test_fetch_flows_empty(monkeypatch):
    monkeypatch.setattr(cf, "http_get", lambda *a, **k: _FakeResp({"data": []}))
    assert cf.fetch_flows(360, "M", "202603") == {}

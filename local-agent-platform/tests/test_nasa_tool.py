import copy
import json
import unittest

import httpx

from src.errors import AgentError
from src.tools.nasa_tool import ENDPOINT, MAX_RESPONSE_BYTES, NasaTool

ARGS = {"start_date": "2015-09-07", "end_date": "2015-09-08"}
FIXTURE = {"element_count": 1, "links": {"self": "secret-key-url"}, "near_earth_objects": {"2015-09-07": [{
    "id": "123", "name": "Example", "is_potentially_hazardous_asteroid": False,
    "estimated_diameter": {"meters": {"estimated_diameter_min": 10, "estimated_diameter_max": 20}},
    "close_approach_data": [{"close_approach_date": "2015-09-07", "miss_distance": {"kilometers": "123456"},
                             "relative_velocity": {"kilometers_per_second": "12.5"}}]}]}}


class NasaTests(unittest.TestCase):
    def make_tool(self, handler):
        return NasaTool("private-api-key", transport=httpx.MockTransport(handler))

    def test_dates_and_restricted_parameters(self):
        tool = NasaTool()
        self.assertEqual(tool.validate(ARGS).start_date, "2015-09-07")
        self.assertEqual(tool.validate({**ARGS, "limit": "3"}).limit, 3)
        for args in ({}, {**ARGS, "start_date": "2015-02-30"}, {**ARGS, "start_date": "20150907"},
                     {**ARGS, "end_date": "2015-09-06"}, {**ARGS, "end_date": "2015-09-15"},
                     {**ARGS, "url": "https://evil.example"}, {**ARGS, "api_key": "x"},
                     {**ARGS, "limit": True}, {**ARGS, "limit": 51}):
            with self.subTest(args=args), self.assertRaises(AgentError):
                tool.validate(args)
        self.assertTrue(tool.available_for("Get NASA asteroid data"))
        with self.assertRaises(AgentError):
            tool.check_task(tool.validate(ARGS), "Read my email")

    def test_exact_endpoint_and_sanitized_result(self):
        def handler(request):
            self.assertEqual(str(request.url).split("?")[0], ENDPOINT)
            self.assertEqual(request.method, "GET")
            self.assertEqual(dict(request.url.params), {**ARGS, "api_key": "private-api-key"})
            return httpx.Response(200, json=FIXTURE)
        tool = self.make_tool(handler)
        result = tool.execute(tool.validate(ARGS))
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["objects"][0]["miss_distance_km"], 123456)
        self.assertNotIn("private-api-key", json.dumps(result))
        self.assertNotIn("secret-key-url", json.dumps(result))
        self.assertNotIn("api_key", json.dumps(tool.definition))

    def test_truncation_counts(self):
        data = copy.deepcopy(FIXTURE)
        data["element_count"] = 2
        data["near_earth_objects"]["2015-09-07"] *= 2
        tool = self.make_tool(lambda request: httpx.Response(200, json=data))
        result = tool.execute(tool.validate({**ARGS, "limit": 1}))
        self.assertEqual(result["total_count"], 2)
        self.assertEqual(result["returned_count"], 1)
        self.assertTrue(result["truncated"])

    def test_http_errors_redirects_timeouts(self):
        for status, code in ((429, "nasa_rate_limit"), (403, "nasa_authentication_error"),
                             (500, "nasa_http_error"), (302, "nasa_http_error")):
            count = []
            def handler(request):
                count.append(request)
                return httpx.Response(status, text="private-api-key", headers={"Location": "https://evil.example"})
            tool = self.make_tool(handler)
            with self.subTest(status=status), self.assertRaises(AgentError) as caught:
                tool.execute(tool.validate(ARGS))
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(len(count), 1)
            self.assertNotIn("private-api-key", str(caught.exception))
        def timeout(request):
            raise httpx.ReadTimeout("private-api-key", request=request)
        tool = self.make_tool(timeout)
        with self.assertRaises(AgentError) as caught:
            tool.execute(tool.validate(ARGS))
        self.assertEqual(caught.exception.code, "nasa_timeout")

    def test_malformed_and_oversized_responses(self):
        for data in ({}, [], {"element_count": True, "near_earth_objects": {}},
                     {"element_count": 9, "near_earth_objects": {}}):
            tool = self.make_tool(lambda request: httpx.Response(200, json=data))
            with self.subTest(data=data), self.assertRaises(AgentError):
                tool.execute(tool.validate(ARGS))
        for content, headers, code in ((b"bad-json", {}, "nasa_response_error"),
                (b"x" * (MAX_RESPONSE_BYTES + 1), {}, "nasa_response_too_large"),
                (b"", {"Content-Encoding": "br"}, "nasa_response_error")):
            tool = self.make_tool(lambda request: httpx.Response(200, content=content, headers=headers))
            with self.assertRaises(AgentError) as caught:
                tool.execute(tool.validate(ARGS))
            self.assertEqual(caught.exception.code, code)

"""Request body helpers.

Flask's request.json returns whatever the body parsed to. `[]`, `"a string"`,
`null` and `123` are all valid JSON, so a route that goes straight to
`data.get("device_id")` raises AttributeError on any of them and the request
becomes a 500 rather than a 400. The same applies one level down: a field that
is present but is a dict where a string was expected reaches `.startswith()` or
a primary-key lookup and fails there instead.

Both are the same mistake — trusting the *shape* of parsed JSON because it
parsed. These two helpers make the check explicit and keep the resulting error
messages identical to the ones the routes already return, so a caller sending a
malformed body sees the same thing as a caller omitting the field.
"""


def json_object(request):
    """The request body as a dict, or None if it is anything else.

    Covers a missing body, an unparseable one, and a valid JSON value that is
    not an object. `silent=True` stops Flask raising on malformed input so the
    route can choose its own response.
    """
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def string_field(data, name):
    """A non-empty string field, or None.

    None is returned for absent, empty, and wrong-typed alike. Routes already
    treat absent and empty the same way, and a value of the wrong type is no
    more usable than a missing one — collapsing them means one error path
    instead of three, and no route has to care which happened.

    Note that bool is deliberately excluded: `isinstance(True, str)` is False,
    so booleans fall through here as they should.
    """
    value = data.get(name)
    return value if isinstance(value, str) and value else None

"""The one strict reading of a tool input, and D_act / D_rec (G3, H1, D10)."""
from __future__ import annotations

import pytest

from semantext import canon


def d(text):
    return canon.d_act(canon.loads(text))


def test_whitespace_and_key_order_do_not_change_the_digest():                         # the control
    assert d('{"b": 1, "a": [true, null, "x"]}') == d('{"a":[true,null,"x"],"b":1}')
    assert canon.dumps(canon.loads('{"b": 1, "a": 2}')) == '{"a":2,"b":1}'


def test_numbers_a_double_cannot_hold_stay_apart():                                    # must-refuse (G3)
    assert d('{"n": 9007199254740993}') != d('{"n": 9007199254740992}')


def test_a_number_keeps_its_text():
    assert canon.dumps(canon.loads('[1.0, 1, 1e2, -0]')) == "[1.0,1,1e2,-0]"


def test_strings_are_byte_exact():                                                     # must-refuse
    assert d('{"p": "rm -rf build"}') != d('{"p": "rm -rf build "}')
    assert d('{"p": "\\u0061"}') == d('{"p": "a"}')    # the same text after reading: one act


def test_keys_sort_by_utf16_code_units():
    # U+1F600 is the pair D83D DE00 in UTF-16, which sorts before U+FB33, though its code point is larger (RFC 8785)
    value = canon.loads('{"\\ufb33": 1, "\\ud83d\\ude00": 2}')
    assert canon.dumps(value).index("\U0001F600") < canon.dumps(value).index("דּ")


@pytest.mark.parametrize("text,word", [
    ('{"a": 1, "a": 2}', "twice"),
    ('{"a": NaN}', "NaN"),
    ('{"a": Infinity}', "Infinity"),
    ('{"a": -Infinity}', "Infinity"),
    ('{"a": 1,}', ""),
    ('{"a": 1} // c', ""),
    ("{'a': 1}", ""),
    ('{"a": "\\ud800"}', "surrogate"),
    ("[" * 300 + "]" * 300, "nested"),
])
def test_the_parser_refuses(text, word):                                               # must-refuse
    with pytest.raises(canon.NotCanonical) as e:
        canon.loads(text)
    assert word in str(e.value)


def test_not_utf8_is_refused():                                                        # must-refuse
    with pytest.raises(canon.NotCanonical):
        canon.loads(b'{"a": "\xff"}')


def test_a_free_form_input_is_its_exact_bytes():                                       # D10
    assert canon.d_act("ls -la") != canon.d_act("ls -la ")
    assert canon.d_act('{"a":1}') != d('{"a": 1}')                                       # never parsed as JSON


def test_a_plain_python_number_has_no_canonical_form():                                # must-refuse
    with pytest.raises(canon.NotCanonical):
        canon.dumps({"n": 1})


def test_d_rec_is_keyed_and_needs_a_key():
    act = d('{"a": 1}')
    assert canon.d_rec(b"k1", act) != canon.d_rec(b"k2", act) != act
    with pytest.raises(canon.NotCanonical):
        canon.d_rec(b"", act)

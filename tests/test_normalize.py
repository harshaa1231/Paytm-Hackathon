from core.normalize import fold, normalize


def test_strips_honorifics_and_descriptors_as_hints():
    n = normalize("Ramesh dudh wala")
    assert n.tokens == ["ramesh"] and n.hints == ["dudh", "wala"]
    n = normalize("Lakshmi amma")
    assert n.tokens == ["laxmi"] and "amma" in n.hints
    n = normalize("Srinivas garu")
    assert n.tokens == ["srinivas"]


def test_initials_and_caps():
    n = normalize("RAMESH K")
    assert n.tokens == ["ramesh"] and n.initials == ["k"]
    n = normalize("Ramesh K. Rao")
    assert n.tokens == ["ramesh", "rao"] and n.initials == ["k"]
    n = normalize("K.RAMESH")
    assert n.tokens == ["ramesh"] and n.initials == ["k"]


def test_transliteration_folds():
    assert fold("lakshmi") == fold("laxmi")
    assert fold("suneeta") == fold("sunita")
    assert fold("kavitha") == fold("kavita")
    assert fold("swathi") == fold("swati")
    assert fold("pooja") == fold("puja")
    assert normalize("VENKATESH").key == "venkatesh"


def test_blank_and_junk():
    assert normalize("").is_blank
    assert normalize(None).is_blank
    assert normalize("  ...  ").is_blank
    assert normalize("Flat 302 auto").is_blank       # only descriptors -> no name tokens
    assert normalize("Raju @#$ 9849012345").tokens == ["raju"]

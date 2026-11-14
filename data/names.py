"""Synthetic Indian name variation for khata names vs UPI names.

Variation types follow the ones IDinsight documents for Indian name matching (transliteration
spellings like Sunita/Suneeta, many Latin spellings of one name), plus initials, reordering,
honorifics, descriptors, all-caps bank names and blank names. All names are synthetic.
"""
from __future__ import annotations

import numpy as np

# first name -> alternative Latin spellings of the same name
FIRST_NAMES: dict[str, list[str]] = {
    "Ramesh": ["Ramesh"], "Suresh": ["Suresh"], "Lakshmi": ["Laxmi", "Lakshmi"], "Sunita": ["Suneeta", "Sunita"],
    "Venkat": ["Venkat", "Venkatesh"], "Srinivas": ["Srinivas", "Sreenivas"], "Anil": ["Anil"], "Sunil": ["Sunil"],
    "Priya": ["Priya", "Preeya"], "Kavita": ["Kavitha", "Kavita"], "Deepak": ["Deepak", "Dipak"],
    "Pooja": ["Pooja", "Puja"], "Rajesh": ["Rajesh"], "Mahesh": ["Mahesh"], "Ganesh": ["Ganesh"],
    "Lalitha": ["Lalita", "Lalitha"], "Geeta": ["Gita", "Geeta"], "Meena": ["Mina", "Meena"],
    "Raju": ["Raju"], "Ravi": ["Ravi"], "Irfan": ["Irfan"], "Ayesha": ["Aisha", "Ayesha"], "Salim": ["Saleem", "Salim"],
    "Joseph": ["Joseph"], "Mary": ["Mary"], "Bijoy": ["Bijoy", "Vijay"], "Anjali": ["Anjali"],
    "Tenzing": ["Tenzin", "Tenzing"], "Lalremruata": ["Lalremruata"], "Bhupen": ["Bhupen"], "Gurpreet": ["Gurpreet"],
    "Harpreet": ["Harpreet"], "Nandini": ["Nandini"], "Padma": ["Padma"], "Sarita": ["Sarita", "Saritha"],
    "Kiran": ["Kiran"], "Manoj": ["Manoj"], "Vinod": ["Vinod"], "Shankar": ["Shankar", "Sankar"],
    "Yamuna": ["Jamuna", "Yamuna"], "Vasanti": ["Basanti", "Vasanti"], "Swati": ["Swathi", "Swati"],
    "Arjun": ["Arjun"], "Farhan": ["Farhan"], "Rekha": ["Rekha"], "Usha": ["Usha"], "Naveen": ["Naveen", "Navin"],
    "Prakash": ["Prakash"], "Durga": ["Durga"], "Sita": ["Seeta", "Sita"], "Govind": ["Govind", "Gobind"],
}
SURNAMES = ["Kumar", "Rao", "Reddy", "Sharma", "Singh", "Das", "Devi", "Naidu", "Khan", "Pillai", "Patel",
            "Gupta", "Verma", "Bora", "Sangma", "Iyer", "Shaikh", "Mathew", "Yadav", "Goud"]
HONORIFICS = ["ji", "bhai", "anna", "amma", "garu", "didi", "akka", "sir", "aunty", "uncle"]
DESCRIPTORS = ["dudh wala", "kirana", "auto", "tailor", "sabzi wali", "watchman", "teacher", "driver",
               "flat 302", "colony", "chai wala", "medical"]
UPI_HANDLES = ["ybl", "okaxis", "oksbi", "paytm", "okhdfcbank", "okicici", "ibl", "axl"]
APPS = ["PhonePe", "Google Pay", "Paytm", "BHIM", "Amazon Pay"]
APP_WEIGHTS = [0.42, 0.33, 0.17, 0.04, 0.04]


def khata_name(rng: np.random.Generator, first: str, surname: str) -> str:
    """How a shopkeeper writes the name in the khata."""
    style = rng.random()
    if style < 0.30:
        return f"{first} {rng.choice(DESCRIPTORS)}"
    if style < 0.55:
        return f"{first} {rng.choice(HONORIFICS)}"
    if style < 0.75:
        return f"{first} {surname}"
    if style < 0.85:
        return f"{first} {surname[0]}."
    return first


def upi_name(rng: np.random.Generator, first: str, surname: str) -> str:
    """What UPI shows: bank-registered name, usually ALL CAPS, often initials, sometimes blank."""
    spelled = str(rng.choice(FIRST_NAMES.get(first, [first])))
    style = rng.random()
    if style < 0.06:
        return ""                                  # VPA only, no name
    if style < 0.40:
        s = f"{spelled} {surname[0]}"
    elif style < 0.70:
        s = f"{spelled} {surname}"
    elif style < 0.80:
        s = f"{surname[0]} {spelled}"              # initial first
    elif style < 0.88:
        s = f"{surname} {spelled}"                 # reversed order
    else:
        s = spelled
    return s.upper()


def vpa(rng: np.random.Generator, first: str) -> str:
    if rng.random() < 0.55:
        local = f"9{rng.integers(100_000_000, 999_999_999)}"
    else:
        local = f"{first.lower()}{rng.integers(10, 9999)}"
    return f"{local}@{rng.choice(UPI_HANDLES)}"


def pick_person(rng: np.random.Generator) -> tuple[str, str]:
    first = str(rng.choice(list(FIRST_NAMES)))
    return first, str(rng.choice(SURNAMES))

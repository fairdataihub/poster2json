"""Tests for the hardening rules of the alto layout engine (layout_streams).

Each test pins one generic rule with a synthetic page: block size noise, two
headings of different columns on one row, margin labels, banners above
columns, and spaced bullet lists.
"""

import pytest

from .test_layout_streams import ls, lines_of, para, run, string, texts

BOLD = "Helvetica-Bold"


def test_block_size_is_rounded_so_float_noise_cannot_decide_a_comparison():
    a = run(string("HEADING ONE", 50, 100, 12.000000096, font=BOLD))
    b = run(string("HEADING TWO", 50, 100, 12.00000009600001, font=BOLD))
    assert a[0].size == b[0].size == 12.0


def test_bold_headings_of_two_columns_on_one_row_are_two_blocks():
    chars = string("Fine-tuning for detection", 50, 100, 14, font=BOLD)
    chars += string("LM adaptation", 400, 100, 14, font=BOLD)
    chars += string("body text of the first column", 50, 130, 10)
    got = texts(run(chars, w=1000))
    assert "Fine-tuning for detection" in got and "LM adaptation" in got
    assert not any("Fine-tuning" in t and "LM adaptation" in t for t in got)


def label_page():
    chars = string("Cells", 20, 100, 14, font=BOLD)
    chars += para("R1", 100, 100, n=3)
    chars += para("R2", 100, 150, n=3)
    chars += string("Stacks", 20, 160, 14, font=BOLD)
    return chars


def test_margin_label_is_read_right_before_the_text_it_names():
    got = [b.lines[0].text.split()[0] for b in run(label_page())]
    assert got == ["Cells", "R1", "Stacks", "R2"]


def test_heading_with_its_paragraph_below_is_not_a_margin_label():
    chars = para("R1", 100, 100, n=3) + para("R2", 100, 150, n=3)
    chars += string("Methods", 20, 100, 14, font=BOLD)
    chars += para("P1", 20, 118, n=2, width_chars=10)
    got = [b.lines[0].text.split()[0] for b in run(chars)]
    assert got[:2] == ["Methods", "P1"]


def test_banner_above_columns_is_read_before_a_left_block_that_starts_below_it():
    chars = string("A banner line that spans columns", 150, 30, 10)
    chars += string("second banner line over them", 150, 42, 10)
    chars += string("Left", 20, 62, 10)
    chars += para("M1", 200, 62, n=2, width_chars=12)
    chars += para("R1", 400, 62, n=2, width_chars=12)
    got = [b.lines[0].text.split()[0] for b in run(chars, w=600)]
    assert got[0] == "A"
    assert got.index("Left") > 0


def test_block_beside_a_column_start_is_not_a_banner():
    # the left column starts above the wide block: hopping stays allowed
    chars = para("L1", 20, 30, n=2, width_chars=10)
    chars += string("wide figure caption over two columns", 150, 60, 10)
    chars += string("L2 tail", 20, 80, 10)
    chars += para("M1", 200, 90, n=2, width_chars=12)
    chars += para("R1", 400, 90, n=2, width_chars=12)
    got = [b.lines[0].text.split()[0] for b in run(chars, w=600)]
    assert got.index("L1") < got.index("L2")


def test_spaced_bullet_items_form_one_block():
    chars = string("• first item of the list", 50, 100, 10)
    chars += string("• second item of the list", 50, 122, 10)
    chars += string("• third item of the list", 50, 144, 10)
    assert len(run(chars)) == 1


def test_spaced_plain_lines_are_still_separate_blocks():
    chars = string("first line of one text", 50, 100, 10)
    chars += string("second line far below it", 50, 122, 10)
    assert len(run(chars)) == 2

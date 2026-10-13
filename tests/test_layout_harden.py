"""Tests for the hardening rules of the alto layout engine (layout_streams).

Each test pins one generic rule with a synthetic page: block size noise, two
headings of different columns on one row, margin labels, banners above
columns, and spaced bullet lists.
"""

import pytest

from .test_layout_streams import lines_of, mk, para, run, string, texts

BOLD = "Helvetica-Bold"


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


def tracked(words, x, y, size=10.0, letter_gap=2.4, word_gap=10.0):
    chars = []
    pos = x
    for word in words:
        for ch in word:
            chars.append(mk(ch, pos, y, size, size * 0.5))
            pos += size * 0.5 + letter_gap
        pos += word_gap - letter_gap
    return chars


def test_letter_spaced_text_becomes_words_again():
    chars = tracked(["Malate", "enzyme"], 50, 100)
    assert lines_of(run(chars)) == ["Malate enzyme"]


def test_even_spacing_without_a_word_boundary_is_left_alone():
    chars = tracked(["abcdefgh"], 50, 100, letter_gap=3.0)
    assert lines_of(run(chars)) == ["a b c d e f g h"]


def test_a_few_short_words_are_not_joined():
    chars = tracked(["a", "b", "c"], 50, 100, letter_gap=2.4, word_gap=2.4)
    assert lines_of(run(chars)) == ["a b c"]


def test_two_raised_middle_dots_over_a_letter_are_a_diaeresis():
    chars = [mk("M", 50, 100, 10, 6.0)]
    chars += [mk("·", 57.5, 96.0, 10, 2.5), mk("·", 60.0, 96.0, 10, 2.5)]
    chars += [mk("u", 56.0, 100, 10, 5.0), mk("n", 61.0, 100, 10, 5.0), mk("z", 66.0, 100, 10, 5.0)]
    assert lines_of(run(chars)) == ["Münz"]


def test_middle_dots_on_the_baseline_are_left_alone():
    chars = string("a", 50, 100, 10) + [mk("·", 56, 100, 10, 2.5), mk("·", 58.5, 100, 10, 2.5)]
    chars += string("b", 61.5, 100, 10)
    assert "¨" not in "".join(lines_of(run(chars)))
    assert "ü" not in "".join(lines_of(run(chars)))


def test_raised_mark_touching_the_next_word_stays_in_its_line():
    # an affiliation number set smaller and higher than the text it leads; its
    # advance is a hair longer than the gap to the next word, which must not be
    # taken for stacked material (the mark would become a block of its own)
    chars = string("Author One, Author Two, on behalf of the Task Force", 100, 100, 36)
    chars += string("1", 100, 160, 24, adv=8.3)
    chars += string("FAIR Data Innovations Hub, San Diego", 108.0, 173.5, 36)
    got = lines_of(run(chars, w=1200, h=800))
    assert any(t.startswith("1 FAIR Data") or t.startswith("1FAIR Data") for t in got), got
    assert "1" not in got


def test_stacked_words_still_split_rows():
    chars = string("first row of text", 100, 100, 20)
    chars += string("second row of text", 100, 124, 20)
    assert lines_of(run(chars)) == ["first row of text", "second row of text"]

import tkinter as tk

from main import ReadmooCheckerApp


class FakeTree:
    def __init__(self):
        self.inserted = []

    def insert(self, _parent, _index, values):
        self.inserted.append(values)


class FakeLabel:
    def __init__(self):
        self.last_config = {}

    def config(self, **kwargs):
        self.last_config.update(kwargs)


def make_app_stub():
    app = ReadmooCheckerApp.__new__(ReadmooCheckerApp)
    app.tree = FakeTree()
    app.status_label = FakeLabel()
    app.after = lambda _delay, func: func()
    return app


def test_populate_tree_inserts_index_title_author():
    app = make_app_stub()
    books = [
        {"title": "Book A", "author": "Author 1"},
        {"title": "Book B", "author": "Author 2"},
    ]

    app.populate_tree(books)

    assert app.tree.inserted == [
        (1, "Book A", "Author 1"),
        (2, "Book B", "Author 2"),
    ]


def test_update_status_sets_black_for_normal_message():
    app = make_app_stub()

    app.update_status("ok", error=False)

    assert app.status_label.last_config["text"] == "ok"
    assert app.status_label.last_config["foreground"] == "black"


def test_update_status_sets_red_for_error_message():
    app = make_app_stub()

    app.update_status("bad", error=True)

    assert app.status_label.last_config["text"] == "bad"
    assert app.status_label.last_config["foreground"] == "red"

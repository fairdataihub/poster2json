"""Example GUI stub - minimal Tkinter example."""

from tkinter import Tk, Label, Button, StringVar, Frame
from tkinter.ttk import Entry  # type: ignore

from . import utils


class Application:
    """Minimal example: feet to meters converter."""

    def __init__(self):
        self.root = Tk()
        self.root.title("Example: Feet to Meters")
        self.root.minsize(300, 100)
        self.feet = StringVar()
        self.meters = StringVar()
        frame = Frame(self.root, padding=10)
        frame.pack(fill="both", expand=True)
        Entry(frame, width=7, textvariable=self.feet).grid(column=1, row=0)
        Label(frame, text="feet").grid(column=2, row=0)
        Label(frame, text="is equivalent to").grid(column=0, row=1)
        Label(frame, textvariable=self.meters).grid(column=1, row=1)
        Label(frame, text="meters").grid(column=2, row=1)
        Button(frame, text="Calculate", command=self.calculate).grid(column=1, row=2)
        self.root.mainloop()

    def calculate(self):
        try:
            self.meters.set(str(utils.feet_to_meters(self.feet.get())))
        except ValueError:
            self.meters.set("?")


def main():
    """Run the example GUI."""
    Application()

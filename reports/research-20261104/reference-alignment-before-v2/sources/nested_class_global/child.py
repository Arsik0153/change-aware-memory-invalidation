def f(x):
    return x
class Outer:
    class Inner:
        global f
        f = 0

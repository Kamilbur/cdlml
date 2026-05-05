CC     = gcc
CFLAGS = -Wall -Wextra -fPIC -shared -O2

all: libtypes.so

libtypes.so: types_lib.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f *.so

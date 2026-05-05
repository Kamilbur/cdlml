CC     = gcc
CFLAGS = -Wall -Wextra -fPIC -shared -O2

all: libarray.so

libarray.so: array_lib.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f *.so

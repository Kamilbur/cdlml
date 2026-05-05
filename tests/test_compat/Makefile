CC=gcc
CFLAGS=-fPIC -shared

libcompat.so: compat_lib.c
	$(CC) $(CFLAGS) -o libcompat.so compat_lib.c

clean:
	rm -f libcompat.so

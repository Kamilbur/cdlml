CC = gcc
CFLAGS=-Wall -ggdb

all: libfoo.so libbar.so libmalloc.so

libmalloc.so: malloc.c
	$(CC) -shared -fPIC -o libmalloc.so malloc.c -ldl -pthread $(CFLAGS)

libfoo.so: foo.c
	$(CC) -shared -o libfoo.so foo.c -ldl $(CFLAGS)

libbar.so: bar.c
	$(CC) -shared -o libbar.so bar.c -ldl $(CFLAGS)


clean:
	rm -rf *.o *.so

.PHONY: all clean
# it goes in infinite loop
# how to repair it?
# all:
all:
	@for dir in $(shell find . -type d); do \
		if [ "$$dir" != "." ] && [ -f "$$dir/Makefile" ]; then \
			$(MAKE) -C $$dir; \
		fi; \
	done
clean:
	@for dir in $(shell find . -type d); do \
		if [ "$$dir" != "." ] && [ -f "$$dir/Makefile" ]; then \
			$(MAKE) -C $$dir clean; \
		fi; \
	done

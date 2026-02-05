CC = gcc
CFLAGS = -Wall -g -I./include \
         -I./opensource/rats-tls/output/include/
LDFLAGS = -lpthread -L/usr/lib64 -lssl -lcrypto -lz -ldl

SRCS = src/main.c src/mig_thread.c src/tmi.c src/tls_core.c src/integrity_check_handler.c
OBJS = $(SRCS:.c=.o)
TARGET = mig-agent

all:$(TARGET)

$(TARGET):$(OBJS)
	$(CC) $^ -o $@ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(TARGET)

debug: CFLAGS += -DDEBUG
debug: $(TARGET)
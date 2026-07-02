#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>

static int is_pts_fd(int fd) {
    char proc_path[64];
    char target[PATH_MAX];
    ssize_t len;

    snprintf(proc_path, sizeof(proc_path), "/proc/self/fd/%d", fd);
    len = readlink(proc_path, target, sizeof(target) - 1);
    if (len < 0) {
        return 0;
    }

    target[len] = '\0';
    return strncmp(target, "/dev/pts/", 9) == 0;
}

static void normalize_model336_termios(struct termios *t) {
    t->c_ispeed = B57600;
    t->c_ospeed = B57600;
    t->c_cflag |= PARENB | PARODD | CLOCAL | CREAD;
    t->c_cflag &= ~CSIZE;
    t->c_cflag |= CS7;
    t->c_cflag &= ~CSTOPB;
#ifdef CRTSCTS
    t->c_cflag &= ~CRTSCTS;
#endif
}

static int is_termios_set_request(unsigned long request) {
    return request == TCSETS || request == TCSETSW || request == TCSETSF;
}

int ioctl(int fd, unsigned long request, ...) {
    static int (*real_ioctl)(int, unsigned long, void *) = NULL;
    va_list ap;
    void *arg;
    int rc;

    if (real_ioctl == NULL) {
        real_ioctl = dlsym(RTLD_NEXT, "ioctl");
        if (real_ioctl == NULL) {
            errno = ENOSYS;
            return -1;
        }
    }

    va_start(ap, request);
    arg = va_arg(ap, void *);
    va_end(ap);

    if (arg != NULL && is_pts_fd(fd) && is_termios_set_request(request)) {
        return 0;
    }

    rc = real_ioctl(fd, request, arg);
    if (rc == 0 && request == TCGETS && arg != NULL && is_pts_fd(fd)) {
        normalize_model336_termios((struct termios *)arg);
    }

    return rc;
}

int tcgetattr(int fd, struct termios *t) {
    static int (*real_tcgetattr)(int, struct termios *) = NULL;
    int rc;

    if (real_tcgetattr == NULL) {
        real_tcgetattr = dlsym(RTLD_NEXT, "tcgetattr");
        if (real_tcgetattr == NULL) {
            errno = ENOSYS;
            return -1;
        }
    }

    rc = real_tcgetattr(fd, t);
    if (rc == 0 && t != NULL && is_pts_fd(fd)) {
        normalize_model336_termios(t);
    }

    return rc;
}

int tcsetattr(int fd, int optional_actions, const struct termios *t) {
    static int (*real_tcsetattr)(int, int, const struct termios *) = NULL;

    if (is_pts_fd(fd) && t != NULL) {
        return 0;
    }

    if (real_tcsetattr == NULL) {
        real_tcsetattr = dlsym(RTLD_NEXT, "tcsetattr");
        if (real_tcsetattr == NULL) {
            errno = ENOSYS;
            return -1;
        }
    }

    return real_tcsetattr(fd, optional_actions, t);
}

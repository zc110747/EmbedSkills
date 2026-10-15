/*
 * probe_fdset.c — 一条命令回答两件事：
 *   1) 本平台的 FD_SETSIZE 是多少、sizeof(fd_set) 多大；
 *   2) 当请求的句柄数超过容量时，FD_SET 是【静默丢弃】还是【越界写】。
 *
 * 构建 / 运行
 *   Windows (MinGW-w64 / MSYS2)：
 *     gcc -O2 -std=c11 probe_fdset.c -o probe_fdset.exe -lws2_32 && ./probe_fdset.exe
 *   Linux / macOS：
 *     cc -O2 -std=c11 probe_fdset.c -o probe_fdset && ./probe_fdset
 *
 * 判读
 *   Windows 默认：FD_SETSIZE=64、sizeof(fd_set)=520、requested=128 → stored=64  ← 静默截断
 *     ⇒ 一个"最多 64 个套接字"的服务只能承载 63 个客户端 + 1 个监听；
 *       第 65 个起 FD_SET 只是不生效，调用方拿不到任何错误。
 *   修复方式（必须在 #include <winsock2.h> 之前）：
 *     #ifndef FD_SETSIZE
 *     #define FD_SETSIZE 8192
 *     #endif
 *   修完后重跑本探针，应看到 FD_SETSIZE=8192、requested=128 → stored=128。
 *
 *   POSIX：FD_SETSIZE 通常是 1024，且 fd_set 是【按描述符号做下标】的位图 ——
 *     FD_SET 一个 >= FD_SETSIZE 的 fd 会写到数组之外（未定义行为，实测常见为踩栈）。
 *     因此本探针在 POSIX 侧刻意不越界；要验证请自己在代码里加边界检查。
 *
 * 说明：本探针不需要 WSAStartup —— FD_ZERO / FD_SET / FD_ISSET 在 Windows 上
 *       也是纯宏，只操作本地结构体。
 */

#include <stdio.h>

#if defined(_WIN32)
#  ifndef WIN32_LEAN_AND_MEAN
#    define WIN32_LEAN_AND_MEAN
#  endif
#  include <winsock2.h>
#  include <ws2tcpip.h>
   typedef SOCKET handle_t;
#else
#  include <sys/select.h>
#  include <sys/time.h>
   typedef int handle_t;
#endif

#if defined(_WIN32)
/* SOCKET 是不透明句柄：任意整数都是一个合法的位位置。
   故意用大值，让"容量"这件事与具体取值无关。 */
#  define H(i) ((handle_t)(0x1000 + (i) * 8))
#  define WANT 128            /* > 64，暴露 Windows 的默认截断 */
#else
/* POSIX 的 fd_set 是按描述符下标索引的位图：fd >= FD_SETSIZE 会越界写。
   刻意留在界内。 */
#  define H(i) ((handle_t)((i) - 1))
#  define WANT ((int)FD_SETSIZE)
#endif

int main(void)
{
  fd_set s;
  int requested = 0;
  int stored = 0;
  int i;

  printf("FD_SETSIZE          = %d\n", (int)FD_SETSIZE);
  printf("sizeof(fd_set)      = %zu bytes\n", sizeof(fd_set));
  printf("sizeof(handle)      = %zu bytes\n", sizeof(handle_t));
#if defined(_WIN32)
  printf("platform            = Windows (FD_SET overflow is SILENT)\n");
#else
  printf("platform            = POSIX  (FD_SET overflow is OUT-OF-BOUNDS)\n");
#endif
  printf("\n");

  FD_ZERO(&s);

  for (i = 1; i <= WANT; ++i) {
    FD_SET(H(i), &s);
    requested = i;
  }

  for (i = 1; i <= requested; ++i) {
    if (FD_ISSET(H(i), &s)) {
      ++stored;
    }
  }

  printf("requested  = %d\n", requested);
  printf("stored     = %d\n", stored);
#if defined(_WIN32)
  printf("fd_count   = %u\n", (unsigned)s.fd_count);
#endif

  printf("\n");
  if (stored < requested) {
    printf("[!] FD_SET SILENTLY TRUNCATED %d of %d handles.\n",
           requested - stored, requested);
    printf("    Effective socket capacity = %d (client slots = capacity - 1 listener).\n",
           stored);
    printf("    Fix: #define FD_SETSIZE <bigger> BEFORE including <winsock2.h>,\n");
    printf("         and make your socket-set wrapper report failure instead of dropping.\n");
    return 1;
  }

  printf("[ok] every requested handle was stored (%d/%d).\n", stored, requested);
#if defined(_WIN32)
  if ((int)FD_SETSIZE <= 64) {
    printf("     NOTE: FD_SETSIZE is still the default 64 - you are at the limit.\n");
  }
#endif
  return 0;
}

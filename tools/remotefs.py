#!/usr/bin/env python3
"""Read-only FUSE passthrough that emulates a remote image layer.

Every request that would cross the network on a remote file system (lookup, getattr, readlink, opendir, readdir,
open, read) waits for a configurable round-trip time before it is answered. Client-side caching is set through the
kernel's FUSE cache timeouts:
  none   no attribute, entry or negative-entry caching: every lookup reaches the server
  short  entries and attributes cached for 1 s, misses not cached (the FUSE default; comparable to NFS defaults)
  long   entries, attributes and misses cached for an hour (safe for an immutable image layer)
File data may stay in the page cache in all modes (keep_cache), so the experiment isolates metadata.
Request counts by type are written to <stats> when the file system is unmounted.
Usage: remotefs.py <source_dir> <mountpoint> <delay_us> <none|short|long> <stats.json>
"""
import errno, json, os, stat, sys, collections
import pyfuse3, trio

SRC, MNT, DELAY_US, CACHE, STATS = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4], sys.argv[5]
TIMEOUT = {"none": 0.0, "short": 1.0, "long": 3600.0}[CACHE]
import ctypes, time
_libc = ctypes.CDLL(None)


def precise_sleep(d):
    """Sleep in a worker thread with minimal timer slack, so short delays are not rounded up."""
    _libc.prctl(29, 1, 0, 0, 0)  # PR_SET_TIMERSLACK = 29, 1 ns
    time.sleep(d)
NEG = CACHE == "long"


class RemoteFS(pyfuse3.Operations):
    def __init__(self):
        super().__init__()
        self.path = {pyfuse3.ROOT_INODE: SRC}; self.ino = {SRC: pyfuse3.ROOT_INODE}; self.next = pyfuse3.ROOT_INODE + 1
        self.dirs = {}; self.n = collections.Counter()

    async def rtt(self, op):
        self.n[op] += 1
        if DELAY_US > 0:
            await trio.to_thread.run_sync(precise_sleep, DELAY_US / 1e6)

    def inode_for(self, p):
        i = self.ino.get(p)
        if i is None:
            i = self.next; self.next += 1; self.ino[p] = i; self.path[i] = p
        return i

    def attrs(self, p, i):
        s = os.lstat(p)
        a = pyfuse3.EntryAttributes()
        for k in ("st_mode", "st_nlink", "st_uid", "st_gid", "st_rdev", "st_size", "st_blksize", "st_blocks"):
            setattr(a, k, getattr(s, k))
        a.st_atime_ns, a.st_mtime_ns, a.st_ctime_ns = s.st_atime_ns, s.st_mtime_ns, s.st_ctime_ns
        a.st_ino = i; a.generation = 0; a.entry_timeout = TIMEOUT; a.attr_timeout = TIMEOUT
        return a

    async def lookup(self, parent, name, ctx=None):
        await self.rtt("lookup")
        p = os.path.join(self.path[parent], os.fsdecode(name))
        try:
            return self.attrs(p, self.inode_for(p)) if os.path.lexists(p) else self.negative()
        except OSError as e:
            raise pyfuse3.FUSEError(e.errno)

    def negative(self):
        if not NEG:
            raise pyfuse3.FUSEError(errno.ENOENT)
        a = pyfuse3.EntryAttributes(); a.st_ino = 0; a.entry_timeout = TIMEOUT; a.attr_timeout = TIMEOUT
        return a

    async def getattr(self, inode, ctx=None):
        await self.rtt("getattr")
        try:
            return self.attrs(self.path[inode], inode)
        except OSError as e:
            raise pyfuse3.FUSEError(e.errno)

    async def readlink(self, inode, ctx):
        await self.rtt("readlink")
        return os.fsencode(os.readlink(self.path[inode]))

    async def opendir(self, inode, ctx):
        await self.rtt("opendir")
        p = self.path[inode]
        try:
            names = sorted(os.listdir(p))
        except OSError as e:
            raise pyfuse3.FUSEError(e.errno)
        self.dirs[inode] = names
        return inode

    async def readdir(self, fh, start_id, token):
        await self.rtt("readdir")
        p = self.path[fh]; names = self.dirs.get(fh) or sorted(os.listdir(p))
        for k in range(start_id, len(names)):
            q = os.path.join(p, names[k])
            try:
                a = self.attrs(q, self.inode_for(q))
            except OSError:
                continue
            if not pyfuse3.readdir_reply(token, os.fsencode(names[k]), a, k + 1):
                break

    async def releasedir(self, fh):
        self.dirs.pop(fh, None)

    async def open(self, inode, flags, ctx):
        await self.rtt("open")
        if flags & (os.O_WRONLY | os.O_RDWR):
            raise pyfuse3.FUSEError(errno.EROFS)
        try:
            fd = os.open(self.path[inode], os.O_RDONLY)
        except OSError as e:
            raise pyfuse3.FUSEError(e.errno)
        return pyfuse3.FileInfo(fh=fd, keep_cache=True)

    async def read(self, fh, off, size):
        await self.rtt("read")
        return os.pread(fh, size, off)

    async def release(self, fh):
        os.close(fh)

    async def statfs(self, ctx):
        s = os.statvfs(SRC); r = pyfuse3.StatvfsData()
        for k in ("f_bsize", "f_frsize", "f_blocks", "f_bfree", "f_bavail", "f_files", "f_ffree", "f_favail"):
            setattr(r, k, getattr(s, k))
        r.f_namemax = s.f_namemax
        return r

    async def getxattr(self, inode, name, ctx):
        raise pyfuse3.FUSEError(errno.ENODATA)

    async def listxattr(self, inode, ctx):
        return []


def main():
    fs = RemoteFS()
    opts = set(pyfuse3.default_options); opts.update({"fsname=remotefs", "ro", "default_permissions", "allow_other"})
    pyfuse3.init(fs, MNT, opts)
    try:
        trio.run(pyfuse3.main)
    finally:
        pyfuse3.close(unmount=False)
        json.dump(dict(fs.n), open(STATS, "w"))


if __name__ == "__main__":
    main()

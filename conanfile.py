from conans import ConanFile, tools
from conans.errors import ConanException
from conans.util.files import load
from conans.client.file_copier import FileCopier
import os
import fnmatch
import re

class GearmanConan(ConanFile):
    name = "Gearman"
    version = "1.1.17"
    license = "BSD"
    url = "https://github.com/kmaragon/conan-gearman"
    description = "libgearman package for Conan"
    settings = "os", "compiler", "build_type", "arch"
    options = {
            "shared": [True, False],
            "server": [True, False],
            "with_mysql": [True,False]
        }
    exports = 'libhashkit-common.h.patch', 'libtest-cmdline.cc.patch', 'worker.cc.patch'

    requires = "Boost/1.60.0@lasote/stable","libevent/2.0.22@theirix/stable","bzip2/1.0.6@kmaragon/stable"
    default_options = "shared=False","server=False","with_mysql=False"
    generators = "gcc"
    libcxx = "stdc++"

    def configure(self):
        self.options["Boost"].shared = True
        self.options["libevent"].shared = True
        self.options["bzip2"].shared = True # Because the Boost package doesn't do this as it needs to
        self.options["Boost"].header_only = False
        self.options["Boost"].without_test = True
        self.options["libevent"].shared = self.options.shared

        if self.options.with_mysql:
            self.requires.add("MySQLClient/6.1.6@hklabbers/stable", private=False)
            self.options["MySQLClient"].shared = self.options.shared

    def source(self):
        tools.download("https://github.com/gearman/gearmand/releases/download/%(1)s/gearmand-%(1)s.tar.gz" % {'1': self.version},
                    "gearman.tar.gz")

        tools.unzip("gearman.tar.gz")
        os.unlink("gearman.tar.gz")

        # Export all of the classes in libgearman-server
        exportre = re.compile('^class ', re.MULTILINE)
        for root, dirnames, filenames in os.walk('gearmand-%s/libgearman-server' % self.version):
            for filename in fnmatch.filter(filenames, '*.h'):
                fn = os.path.join(root, filename)
                content = re.sub('^\s+class ', 'class GEARMAN_API ', load(fn), 0, flags=re.MULTILINE).encode('utf-8')
                with open(fn, "wb") as handle:
                    handle.write(content)

        # Apply our patches so we can compile on non-glibc
        self.run('cd gearmand-%s && patch -p1 < ../libhashkit-common.h.patch && patch -p1 < ../libtest-cmdline.cc.patch && patch -p1 << ../worker.cc.patch' % self.version)

    def unquote(self, str):
        if str.startswith('"'):
            str = str[1:]
        if str.endswith('"'):
            str = str[:-1]

        return str

    def build(self):
        # extract the boost lib dir
        boost_libdir=""
        mysql_libdir=""
        libevent_libdir=""
        finished_package = os.getcwd() + "/pkg"

        flags = load("conanbuildinfo.gcc").split()
        for fl in flags:
            if fl[0:2] == '-L':
                if re.match('.*[^A-Za-z0-9_\\-]Boost[^A-Za-z0-9_\\-]', fl):
                    boost_libdir = self.unquote(fl[2:])
                elif re.match('.*[^A-Za-z0-9_\\-]MySQLClient[^A-Za-z0-9_\\-]', fl):
                    mysql_libdir = self.unquote(fl[2:])
                elif re.match('.*[^A-Za-z0-9_\\-]libevent[^A-Za-z0-9_\\-]', fl):
                    libevent_libdir = self.unquote(fl[2:])

        make_options = os.getenv("MAKEOPTS") or ""
        if not re.match("/[^A-z-a-z_-]-j", make_options):
            cpucount = tools.cpu_count()
            make_options += " -j %s" % (cpucount * 2)

        shared_flags = '--enable-static --disable-shared' if not self.options.shared else '--disable-static'
        cflags = '-I"%s/../include" -I"%s/../include"' % (boost_libdir, libevent_libdir)

        os.environ["C_INCLUDE_PATH"] = "%s/../include" % libevent_libdir
        os.environ["CPLUS_INCLUDE_PATH"] = "%s/../include" % libevent_libdir

        if self.options.with_mysql:
            cflags += '-I"%s/../include" ' % mysql_libdir
        
        # apparently the autotools m4 config that gearman set up for
        # libevent checking can't handle quoted libraries
        boost_libdir = boost_libdir.replace(' ', '\\ ')
        libevent_libdir = libevent_libdir.replace(' ', '\\ ')
        mysql_libdir = mysql_libdir.replace(' ', '\\ ')

        rpathdirs = ""

        if self.options.with_mysql:
            os.environ["LIBS"] = '-L%s -L%s -L%s' % (boost_libdir, libevent_libdir, mysql_libdir)
            rpathdirs = "%s:%s:%s" % (boost_libdir, libevent_libdir, mysql_libdir)
        else:
            os.environ["LIBS"] = '-L%s -L%s' % (boost_libdir, libevent_libdir)
            rpathdirs = "%s:%s" % (boost_libdir, libevent_libdir)

        if self.options.server:
            cflags += " -Wl,-E"

        os.environ["CFLAGS"] = cflags
        os.environ["CXXFLAGS"] = cflags
        os.environ["LD_LIBRARY_PATH"] = libevent_libdir
        os.environ["LIBS"] += " -Wl,-E"

        # sigh... gearman
        libs = ""
        if self.options.with_mysql:
            libs = "-lmysqlclient"

        if not self.options.shared:
            os.environ["LIBS"] += "-ldl -l%s %s" % (self.libcxx, libs)
        else:
            os.environ["LIBS"] += libs

        mysql_flags = "--without-mysql"
        if self.options.with_mysql:
            mysql_flags = "--with-mysql=\"%s/..\"" % mysql_libdir

        # TODO: make these flags if someone needs them and set up the deps
        mysql_flags += " --without-sqlite3 --without-postgresql"

        command = 'configure %s --prefix="%s" --with-boost="%s/.." %s' % \
                (mysql_flags, finished_package, boost_libdir, shared_flags)

        self.output.info("Running %s" % command)
        self.run("cd gearmand-%s && ./%s" % (self.version, command))
        self.run("cd gearmand-%s && make %s && make install" % (self.version, make_options))

        if self.options.server:
            archive = "gearmand-%s/libgearman-server/.libs/libgearman-server.a" % self.version
            if self.options.shared:
                # we need to build a shared version of the server
                self.run('g++ -o "%s/lib/libgearman-server.so" -shared -rdynamic ' % finished_package +
                        ' -Wl,--whole-archive -fvisibility=default %s "%s" -Wl,--no-whole-archive' % (os.getenv("LDFLAGS") or "", archive) +
                        ' -Wl,-rpath -Wl,"%s" %s -levent -lboost_program_options' % (rpathdirs, os.environ["LIBS"]))
            else:
                # just copy the archive
                self.run('cp "%s" "%s/lib"' % (archive, finished_package))

            # copy the relevant include files from server
            cp = FileCopier("%s/gearmand-%s" % (os.getcwd(), self.version), finished_package)
            cp("*.h*", dst="include/libgearman-server", src="libgearman-server")

            # we also need the whole suite of files from libgearman
            cp("*.h", dst="include/libgearman", src="libgearman")
            cp("*.h", dst="include", src=".")

    def package(self):
        self.copy("*", dst="lib", src="pkg/lib", links=True)
        self.copy("*", dst="bin", src="pkg/bin", links=True)
        self.copy("*", dst="sbin", src="pkg/bin", links=True)
        self.copy("*", dst="include", src="pkg/include", links=True)


    def package_info(self):
        libs = ["gearman"]
        if self.options.server:
            libs += ["gearman-server"]

        self.cpp_info.libs = libs
        self.cpp_info.libdirs = ["lib"]
        self.cpp_info.includedirs = ["include"]
        self.cpp_info.bindirs = ["bin"]


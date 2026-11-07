set -eu
cd /home/dukto/private-read-r113-diagnostic
nice -n 10 g++ -std=c++14 -fPIC -pthread -Isrc probe.cpp build/CMakeFiles/dukto-core.dir/src/core/error.cpp.o build/CMakeFiles/dukto-core.dir/src/core/files.cpp.o build/CMakeFiles/dukto-core.dir/src/core/nativecommit.cpp.o build/CMakeFiles/dukto-core.dir/src/core/sourcefile.cpp.o build/CMakeFiles/dukto-core.dir/src/core/filecredit.cpp.o build/CMakeFiles/dukto-core.dir/src/core/privatestore.cpp.o $(pkg-config --cflags --libs Qt5Core Qt5Network) -o probe-minimal > probe-minimal-build.log 2>&1
./probe-minimal > probe-minimal-result.json
cat probe-minimal-result.json

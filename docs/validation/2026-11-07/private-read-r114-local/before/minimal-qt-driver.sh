set -eu
cd /home/dukto/private-read-r113-diagnostic
test -d /usr/include/x86_64-linux-gnu/qt5/QtCore
nice -n 10 g++ -std=c++14 -fPIC -pthread -Isrc -I/usr/include/x86_64-linux-gnu/qt5 -I/usr/include/x86_64-linux-gnu/qt5/QtCore -I/usr/include/x86_64-linux-gnu/qt5/QtNetwork probe.cpp build/CMakeFiles/dukto-core.dir/src/core/error.cpp.o build/CMakeFiles/dukto-core.dir/src/core/files.cpp.o build/CMakeFiles/dukto-core.dir/src/core/nativecommit.cpp.o build/CMakeFiles/dukto-core.dir/src/core/sourcefile.cpp.o build/CMakeFiles/dukto-core.dir/src/core/filecredit.cpp.o build/CMakeFiles/dukto-core.dir/src/core/privatestore.cpp.o -lQt5Core -lQt5Network -o probe-minimal-qt > probe-minimal-qt-build.log 2>&1
./probe-minimal-qt > probe-minimal-qt-result.json
cat probe-minimal-qt-result.json

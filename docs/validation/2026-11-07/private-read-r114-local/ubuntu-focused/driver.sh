set -eu
cd /home/dukto/private-read-r114-validation
cp CMakeLists-validation.txt CMakeLists.txt
cmake -S . -B candidate-build -G Ninja -DCMAKE_BUILD_TYPE=Release > configure.log 2>&1
nice -n 10 cmake --build candidate-build --parallel 2 > build.log 2>&1
sha256sum candidate-build/probe candidate-build/private-read-tests > binaries-before.sha256
candidate-build/private-read-tests -o qt.log,txt -o qt.xml,junitxml
candidate-build/probe > probe-result.json
sha256sum candidate-build/probe candidate-build/private-read-tests > binaries-after.sha256
cmp binaries-before.sha256 binaries-after.sha256
cat probe-result.json

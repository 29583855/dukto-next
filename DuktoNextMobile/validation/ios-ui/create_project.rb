# 日期：2026-11-26；独立系统UI测试宿主通过bundleIdentifier访问已安装产品，不修改应用。
require 'xcodeproj'
require 'fileutils'

project_path, source_path = ARGV
FileUtils.mkdir_p(File.dirname(project_path))
project = Xcodeproj::Project.new(project_path)
target = project.new_target(:ui_test_bundle, 'MobileSendTests', :ios, '15.0')
file = project.main_group.new_file(File.expand_path(source_path))
target.add_file_references([file])
target.build_configurations.each do |config|
  config.build_settings['PRODUCT_BUNDLE_IDENTIFIER'] = 'org.duktonext.validation.sendtests'
  config.build_settings['SWIFT_VERSION'] = '5.0'
  config.build_settings['GENERATE_INFOPLIST_FILE'] = 'YES'
  config.build_settings['CODE_SIGNING_ALLOWED'] = 'NO'
  config.build_settings['CODE_SIGNING_REQUIRED'] = 'NO'
  config.build_settings['TARGETED_DEVICE_FAMILY'] = '1,2'
  config.build_settings['SUPPORTED_PLATFORMS'] = 'iphonesimulator'
end
project.save
scheme = Xcodeproj::XCScheme.new
scheme.add_build_target(target)
scheme.add_test_target(target)
scheme.save_as(project_path, 'MobileSendTests', true)

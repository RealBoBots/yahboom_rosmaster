from glob import glob

from setuptools import find_packages, setup

package_name = "jar_bringup"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
        ("share/" + package_name + "/rviz", glob("rviz/*.rviz")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Emiliano Bongiovanni",
    maintainer_email="bongiovanni.9@gmail.com",
    description="Challenge JAR 2026 bringup for the ROSMASTER X3 simulation.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "drive_check = jar_bringup.drive_check:main",
            "keyboard_teleop = jar_bringup.keyboard_teleop:main",
        ],
    },
)

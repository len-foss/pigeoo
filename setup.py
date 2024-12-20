# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html).

import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

name = "pigeoo"
url_root = f"https://github.com/len-foss/{name}"

setuptools.setup(
    name=name,
    version="0.0.4.1",
    author="len-foss",
    author_email="nans.lefebvre@acsone.eu",
    description="Odoo Documentation Generator",
    long_description=long_description,
    long_description_content_type="text/markdown",
    install_requires=["click>=7.1.2", "ConfigArgParse>=1.3", "lxml>=4.6.2"],
    url=url_root,
    license="LGPLv3+",
    project_urls={"Bug Tracker": f"{url_root}/issues"},
    classifiers=[
        "Programming Language :: Python :: 3.8",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: "
        "GNU Lesser General Public License v3 or later (LGPLv3+)",
        "Programming Language :: Python :: 3.8",
        "Framework :: Odoo",
    ],
    include_package_data=True,
    packages=setuptools.find_packages(include=[f"{name}", f"{name}.*"]),
    python_requires=">=3.8",
    entry_points=f"""
        [console_scripts]
        {name}={name}.main:main
    """,
)

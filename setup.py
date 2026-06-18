from setuptools import setup, find_packages

setup(
    name="job-alert-scorer",
    version="0.1.0",
    description="Read job-alert emails, fetch descriptions, and score fit with AI.",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=[
        "google-auth>=2.28.0",
        "google-auth-oauthlib>=1.2.0",
        "google-auth-httplib2>=0.2.0",
        "google-api-python-client>=2.120.0",
        "cryptography>=41,<44",
        "requests>=2.31.0",
        "beautifulsoup4>=4.12.0",
        "pyyaml>=6.0",
        "python-dotenv>=1.0",
        "anthropic>=0.49.0",
    ],
    extras_require={
        "openai": ["openai>=1.0"],
        "google": ["google-generativeai>=0.5"],
        "groq": ["groq>=0.4"],
    },
)

# Contributing to Zeython

Thank you for considering contributing to **Zeython**! We welcome contributions to improve the project, whether it's fixing bugs, adding new features, or enhancing documentation. Follow this guide to get started with contributing.

## How Can You Contribute?

### 1. Reporting Bugs
If you find any bugs, please open an issue in the repository and include:
- A clear description of the bug.
- Steps to reproduce the issue.
- Any relevant error messages or screenshots.

### 2. Suggesting Features or Improvements
If you have ideas for features or improvements, please open an issue with:
- A detailed description of the feature or improvement.
- How it benefits the project.
- If possible, include any references or examples.

### 3. Submitting Code Contributions

#### **Forking the Repository**
1. Fork the repository by clicking the "Fork" button on GitHub.
2. Clone your fork locally:
   ```bash
   git clone https://github.com/zaber-dev/Zeython.git
   cd your-fork
   ```

#### **Creating a New Branch**
Always create a new branch for your changes to avoid polluting the `main` branch:
```bash
git checkout -b feature-or-bugfix-description
```

#### **Making Changes**
- Ensure that your code follows the project's structure.
- If you're adding a new feature:
  - Follow the MVC architecture.
  - Update or create relevant views, controllers, models, or commands.
- If you're fixing a bug, add a detailed explanation in the pull request.

#### **Writing Tests**
- If you're adding a new feature or fixing a bug, consider writing tests to ensure the changes work as expected.
- Place your tests in an appropriate testing file (to be created if needed).

#### **Commit Messages**
- Write clear and descriptive commit messages.
- Follow the format:
  ```
  Fix: Corrected pagination bug in Actions.
  Feature: Added new Discord slash command for user stats.
  ```

#### **Pushing Your Changes**
```bash
git push origin feature-or-bugfix-description
```

#### **Creating a Pull Request**
- Go to your fork on GitHub and click the "Compare & Pull Request" button.
- Write a description of your changes in the PR.
- Reference any related issues in the PR.
- Request a review from one of the maintainers.

## Code Style

- Follow **PEP8** for Python code.
- Use clear and descriptive variable and function names.
- Keep functions and methods small and focused.
- Comment your code where necessary, especially for complex logic.
- Ensure that any changes to the database layer are handled cleanly.

## Development Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/zaber-dev/Zeython.git
   cd your-repo
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up Environment Variables**:
   Create a `.env` file in the root directory with necessary environment variables.

4. **Run the Application**:
   ```bash
   python config/boot.py
   ```

5. **Run Tests** (if available):
   ```bash
   pytest
   ```

6. **Docker (Optional)**:
   If you'd like to work in a Docker environment:
   ```bash
   docker build -t zeython .
   docker run -d -p 5000:5000 zeython
   ```

## Contributor License Agreement (CLA)

By submitting code to this repository, you agree that your contributions will be licensed under the same license as the project: **GNU General Public License v3.0**.

## Communication

If you have any questions or need assistance, feel free to reach out by:
- Opening an issue.
- Mailing me at: zaber@zealtyro.com

Thank you for helping to improve this project! 😊

---

For a more detailed contributor environment and workflow, see the Developer Setup guide:

- docs/developer-setup.md

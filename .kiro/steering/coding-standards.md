---
inclusion: auto
---

# Coding Standards and Best Practices

## General Principles

### Code Quality
- Write clean, readable, self-documenting code
- Follow language-specific style guides
- Use meaningful variable and function names
- Keep functions small and focused (single responsibility)
- Avoid deep nesting (max 3-4 levels)
- Comment complex logic, not obvious code

### DRY (Don't Repeat Yourself)
- Extract common logic into reusable functions/modules
- Use configuration files for repeated values
- Create shared libraries for cross-project code

### Error Handling
- Handle errors explicitly, don't ignore them
- Provide meaningful error messages
- Log errors with context
- Fail fast and loudly in development
- Graceful degradation in production

## Language-Specific Standards

### TypeScript/JavaScript
- Use TypeScript for type safety
- Enable strict mode
- Use const/let, never var
- Prefer async/await over callbacks
- Use ESLint and Prettier
- Follow Airbnb or Standard style guide

### Python
- Follow PEP 8 style guide
- Use type hints (Python 3.6+)
- Use Black for formatting
- Use pylint or flake8 for linting
- Write docstrings for functions/classes
- Use virtual environments

### Go
- Follow official Go style guide
- Use gofmt for formatting
- Use golint and go vet
- Handle errors explicitly
- Use meaningful package names
- Write table-driven tests

### Java
- Follow Google Java Style Guide
- Use Maven or Gradle for builds
- Write unit tests with JUnit 5
- Use Lombok to reduce boilerplate
- Implement proper exception handling
- Use SLF4J for logging

### YAML
- Use 2 spaces for indentation
- Quote strings when necessary
- Use consistent key ordering
- Validate with yamllint
- Keep files under 500 lines

## Git Practices

### Commit Messages
Follow conventional commits format:
```
<type>(<scope>): <subject>

<body>

<footer>
```

Types: feat, fix, docs, style, refactor, test, chore

Example:
```
feat(backstage): add Kro plugin integration

- Implement RGD discovery
- Add ResourceGroup management
- Integrate with catalog

Closes #123
```

### Branch Naming
- `feature/<description>`: New features
- `fix/<description>`: Bug fixes
- `chore/<description>`: Maintenance tasks
- `docs/<description>`: Documentation updates

### Pull Requests
- Keep PRs focused and small
- Write descriptive PR descriptions
- Link related issues
- Request reviews from relevant team members
- Ensure CI passes before merging

## Testing Standards

### Test Coverage
- Aim for 80%+ code coverage
- Focus on critical paths
- Test edge cases and error conditions
- Mock external dependencies

### Test Organization
- Unit tests: Test individual functions/methods
- Integration tests: Test component interactions
- E2E tests: Test complete workflows
- Keep tests independent and isolated

### Test Naming
Use descriptive test names:
```typescript
describe('UserService', () => {
  describe('createUser', () => {
    it('should create user with valid data', async () => {
      // test implementation
    });
    
    it('should throw error when email is invalid', async () => {
      // test implementation
    });
  });
});
```

## Documentation

### Code Documentation
- Document public APIs and interfaces
- Explain "why" not "what" in comments
- Keep documentation close to code
- Update docs when code changes

### README Files
Every project/module should have a README with:
- Purpose and overview
- Prerequisites
- Installation instructions
- Usage examples
- Configuration options
- Contributing guidelines

### API Documentation
- Use OpenAPI/Swagger for REST APIs
- Document all endpoints, parameters, responses
- Provide example requests/responses
- Keep documentation in sync with code

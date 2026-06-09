Trước tiên hãy đọc:

* `SEP490_Children-s-Toy_Backend/CODING_RULES.md`
* Toàn bộ source code của project `SEP490_Children-s-Toy_AI` hiện tại.

Sau đó hãy phân tích kiến trúc hiện tại và đề xuất phương án **refactor theo hướng Backend Architecture** để codebase rõ ràng, dễ mở rộng và dễ bảo trì hơn.

## Current Context

Project AI hiện tại không chỉ bao gồm:

### AI Moderation

* Text Moderation
* Image Moderation
* Product Review Moderation

### AI Content Generation

* Auto Blog Generation

Trong tương lai có thể mở rộng thêm:

* Product Description Generation
* Product Classification
* Recommendation Engine
* AI Assistant
* AI Workflow Automation
* Các AI Features khác

Do đó tôi muốn thiết kế project theo hướng một **AI Platform Backend** thay vì chỉ phục vụ riêng một use case.

---

## Current Problem

Codebase hiện tại đang phát triển theo hướng feature-first/prototype nên tôi muốn đánh giá lại:

* Business logic có đang nằm lẫn trong API layer hay không.
* Logic gọi AI có đang bị duplicate hay không.
* Có đang truy cập database trực tiếp từ nhiều nơi hay không.
* Có đang phụ thuộc quá chặt vào provider cụ thể hay không.
* Có dễ mở rộng thêm AI features mới hay không.
* Có dễ thay đổi model/provider trong tương lai hay không.

---

## Architecture Analysis Request

Hãy phân tích và đề xuất kiến trúc phù hợp nhất cho project này.

So sánh:

* Layered Architecture
* Clean Architecture
* Onion Architecture
* Hexagonal Architecture
* Vertical Slice Architecture

Đánh giá theo:

* Maintainability
* Scalability
* Testability
* Development Speed
* Learning Curve
* Suitability cho AI Platform

---

## Preferred Direction

Tôi muốn kiến trúc gần với Backend truyền thống:

```text
API
↓
Service
↓
Repository
↓
Database
```

nhưng vẫn hỗ trợ tốt cho nhiều AI modules và nhiều AI providers.

Hãy đánh giá xem đây có phải lựa chọn phù hợp nhất không.

---

## Proposed Architecture

Ví dụ:

```text
API
↓
Application Services
↓
AI Domain Services / Engines
↓
Repositories
↓
Database
```

và

```text
Application Services
↓
AI Providers
```

---

## Responsibilities

### API Layer

Ví dụ:

```text
/api
```

Chỉ chịu trách nhiệm:

* Routing
* Authentication
* Authorization
* Request Validation
* Response Mapping

Không chứa business logic.

---

### Application Services

Ví dụ:

```text
ModerationService
BlogGenerationService
```

Chịu trách nhiệm:

* Business Rules
* Workflow Orchestration
* Transaction Handling
* Feature Logic

Ví dụ:

```text
ReviewModerationWorkflow
BlogGenerationWorkflow
```

---

### AI Domain Layer

Ví dụ:

```text
ModerationEngine
ContentGenerationEngine
PromptBuilder
PromptTemplateManager
ContentAnalyzer
```

Chịu trách nhiệm:

* AI-specific business logic
* Prompt construction
* Response interpretation
* Classification logic
* AI workflow execution

Không phụ thuộc API layer.

---

### AI Provider Layer

Tôi hiện đang sử dụng các nhà cung cấp/model như:

```text
Groq
DeepSeek
```

và có thể bổ sung thêm trong tương lai:

```text
OpenAI
Gemini
Claude
Ollama
```

Tôi muốn đánh giá cách thiết kế provider abstraction.

Ví dụ:

```text
AIProvider (interface)
│
├── GroqProvider
├── DeepSeekProvider
├── OpenAIProvider
├── GeminiProvider
└── ClaudeProvider
```

Mục tiêu:

* dễ thay đổi provider
* dễ fallback giữa nhiều providers
* dễ A/B testing model
* không để business logic phụ thuộc Groq hay DeepSeek

---

### Repository Layer

Ví dụ:

```text
ModerationRepository
BlogRepository
PromptTemplateRepository
```

Chỉ xử lý:

* CRUD
* Query
* Persistence

Không chứa AI logic.

---

### Database Layer

Ví dụ:

```text
Models
Database Context
Migrations
Configurations
```

---

## Folder Structure Proposal

Hãy đề xuất structure phù hợp.

Ví dụ:

```text
src/
├── api/
├── application/
│   ├── moderation/
│   ├── blog_generation/
│   └── shared/
├── ai/
│   ├── providers/
│   │   ├── base/
│   │   ├── groq/
│   │   ├── deepseek/
│   │   └── ...
│   ├── engines/
│   ├── prompts/
│   └── models/
├── repositories/
├── database/
├── schemas/
├── integrations/
├── configs/
├── utils/
└── tests/
```

hoặc structure tốt hơn nếu phù hợp.

---

## Dependency Rules

Hãy xác định rõ dependency direction:

```text
API
→ Application Service
→ AI Engine
→ Provider Abstraction
→ Provider Implementation

API
→ Application Service
→ Repository
→ Database
```

Và các dependency bị cấm.

Ví dụ:

❌ API gọi trực tiếp Database

❌ API gọi trực tiếp Groq SDK

❌ Repository gọi Provider

❌ Provider truy cập Database

❌ Controller chứa AI Prompt Logic

---

## AI-Specific Design Questions

Đề xuất cách triển khai:

### Moderation Module

```text
ReviewModerationService
↓
ModerationEngine
↓
AIProvider
↓
GroqProvider / DeepSeekProvider
```

### Blog Generation Module

```text
BlogGenerationService
↓
ContentGenerationEngine
↓
PromptBuilder
↓
AIProvider
↓
GroqProvider / DeepSeekProvider
```

Làm sao để:

* thay đổi model dễ dàng
* đổi provider không ảnh hưởng business logic
* hỗ trợ fallback khi provider lỗi
* hỗ trợ nhiều model cho từng use case

Ví dụ:

```text
Moderation
→ DeepSeek

Blog Generation
→ Groq

Fallback
→ OpenAI
```

---

## Migration Plan

Dựa trên source code hiện tại:

* Những file nào nên chuyển sang Application Services.
* Những file nào nên chuyển sang AI Engine.
* Những file nào nên chuyển sang Provider Layer.
* Những file nào nên chuyển sang Repository.
* Thứ tự refactor an toàn nhất.
* Những technical debts cần xử lý trước.

---

## Final Recommendation

Cuối cùng hãy đưa ra recommendation cụ thể:

* Kiến trúc nên dùng tên gọi gì.
* Có phải pattern phổ biến trong Backend không.
* Có phù hợp với AI Platform sử dụng nhiều AI providers không.
* Có nên dùng Layered Architecture thuần túy hay Layered Architecture + AI Domain Layer.

Mục tiêu là xây dựng một AI Platform có thể mở rộng nhiều tính năng AI trong tương lai, hỗ trợ nhiều providers (Groq, DeepSeek, OpenAI, Gemini, Claude...), dễ bảo trì, dễ test và không bị phụ thuộc vào bất kỳ nhà cung cấp AI nào.

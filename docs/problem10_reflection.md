# Problem 10: Reflection
## Campus Customs Multi-Agent Operations

### 1. How did the agents perform on each ticket?

What I found most interesting about this project was that the agents generally had access to the information they needed, but that didn't necessarily mean they knew what to do with it. Building a multi-agent system made me think less about whether AI can complete individual tasks and more about how effectively it can coordinate work, interpret responsibilities, and recognize when a decision requires human judgment.

Ticket 102 was probably the clearest example of the system working as intended. Mario recognized that the rent notice required Facilities and Accounting rather than involving the entire team. Ryu verified the notice against the lease, Spyro checked the available funds and prepared the payment request, and the system stopped for human approval. The payment was executed only after I authorized it. This was an effective division of responsibilities, and the agents didn't waste time involving specialists who had nothing to contribute.

Ticket 101 exposed a different problem. The agents correctly identified the inventory shortage, the unpaid supplier invoice, and the need for human approval before making a payment. However, Sonic included internal invoice and payment information in the customer-facing response. The information wasn't fabricated, but it was still inappropriate to share. This demonstrated that factual accuracy and good judgment are not the same thing. An AI agent can provide technically correct information while still making a poor communication decision.

Ticket 103 was probably the most useful learning experience because the initial run didn't produce the action I expected. Spyro understood the inventory shortage and could explain the discount policy, but never submitted a discount request. It interpreted the absence of a customer-proposed price as a reason not to proceed, even though proposing a price within the established guidelines was part of Accounting's responsibility. Spyro also used a generic product description instead of the actual SKU during one lookup. These weren't problems with the underlying arithmetic. They were problems with interpreting the assignment and translating available information into action.

We addressed these issues by clarifying the agents' responsibilities and rerunning the ticket while preserving the original results. This demonstrated that improving an AI system doesn't always require more tools or better data. Sometimes the problem is how a task is framed or what assumptions an agent makes about its own authority.

### 2. How did the actual results compare with my expected plans?

For Ticket 102, the actual delegation matched my expected plan exactly. Mario involved Ryu first to verify the lease, and Ryu delegated the financial work to Spyro. The agents used the appropriate tools and prepared the $2,400 rent request without involving Inventory or Customer Service. After I approved the payment, the ticket was operationally resolved.

Ticket 101 also followed the expected delegation structure. Mario involved Crash, Crash brought in Spyro to handle the overdue invoice, and Mario involved Sonic to draft the customer response. Crash additionally used `list_vendors`, which made sense given the inventory shortage. The main deviation wasn't the delegation structure but the quality of Sonic's output. I expected a customer-appropriate response based on confirmed information, but Sonic exposed confidential internal details. The draft was preserved for evaluation rather than sent.

Ticket 103 was different because the initial delegation structure was correct, but the expected action didn't occur. Mario involved Crash, Spyro, and Sonic as planned. However, Spyro never called `request_discount`, so the human approval gate I expected never appeared. It also failed an inventory lookup by using "hoodie" instead of the actual SKU. After we clarified responsibility for proposing the discount and using exact identifiers, the second run followed the intended workflow.

The most interesting distinction was that the agents could follow the correct organizational structure without necessarily producing the correct outcome. Delegating to the right person doesn't guarantee that the person understands what decision they're responsible for making.

The Cash tab also confirmed the importance of keeping decisions and transactions separate. We started with $3,400, approved $2,400 for rent and $840 for the supplier invoice, and finished with $160. The hoodie discount did not change checking because approving a selling price isn't the same as paying an expense. The final balance matched the database.

### 3. What would have been simpler with one agent using all the tools?

I think Ticket 102 would have been easier to execute with one agent.

The workflow was relatively predictable: verify the rent notice against the lease, check the checking balance, and prepare a payment request. It didn't require much interpretation or collaboration between different functions. The multi-agent approach completed it successfully, but it required 10 model requests and 22,772 tokens to move through the delegation structure. A single agent with access to those tools could probably have completed the same investigation with less communication overhead.

Ticket 103 also demonstrated how handoffs can introduce unnecessary confusion. Mario's initial instructions to Spyro framed the proposed price as information that needed to come from the customer. Spyro followed that interpretation rather than recognizing that recommending a price was part of its responsibility. A single agent might have avoided that particular misunderstanding because the inventory, pricing, and approval-preparation tasks would have remained within one context.

However, I wouldn't necessarily conclude that a single agent is better overall. Separating responsibilities also created meaningful boundaries. Only Accounting could submit financial approval requests, and Customer Service didn't need access to the shop's internal financial tools. Those boundaries made the system easier to supervise, even if they introduced additional coordination costs.

To me, this suggests that the decision to use multiple agents should depend on whether specialization and accountability add enough value to justify the additional complexity. More agents don't automatically mean better performance.

### 4. What three new problems could this team solve with its current tools?

**First, the team could investigate another rent notice.** The lease database records the next rent due date, so Facilities could verify a new notice against the lease and Accounting could assess whether the payment was affordable. The team could prepare an approval request when funding permits. It wouldn't need an entirely new workflow because it already demonstrated this capability on Ticket 102.

**Second, the team could evaluate a new order for the blue campus caps.** The inventory database contains stock for `CC-HAT-BLUE`. Inventory could check available quantities, sizes and pricing, Accounting could evaluate the financial implications if necessary, and Customer Service could draft an accurate response describing what the store could fulfill. A routine order within available inventory would be a relatively straightforward application of the existing tools.

**Third, the team could investigate another request for a group discount.** Inventory could verify the requested products and quantities, Accounting could evaluate the proposed price against the simulation's discount policy, and Customer Service could draft a response explaining what could actually be offered. Human approval would still be required before confirming the discount.

These are problems the existing system is reasonably equipped to evaluate because they rely on information already present in its database and tools.

### 5. What three new problems couldn't this team solve, and what would it need?

**First, the team couldn't solve an ongoing cash shortage by generating revenue.** At the end of our simulation, checking contained only $160, while the next monthly rent obligation was $2,400. Accounting could identify the shortfall, but none of the agents could process sales, record incoming revenue, or forecast collections using actual transaction data. I would add sales and accounts-receivable tools, along with a Finance or Sales agent capable of analyzing expected revenue and cash flow. Any financial decisions would still need appropriate authorization.

**Second, the team couldn't properly receive and record new inventory when a shipment arrived.** It could check existing stock and identify shortages, but there wasn't a tool to verify a delivery, record received quantities, or update inventory from a physical shipment. I would add shipment-tracking and inventory-receiving tools. Inventory could retain responsibility for the process, although a dedicated Receiving agent might be useful if the operation became more complex. Ideally, the system would require confirmation that the merchandise physically arrived before adding it to available stock.

**Third, the team couldn't actually communicate with customers or verify whether an offer was accepted.** Sonic could draft a response, but the system couldn't send it, record a reply, or establish that the customer agreed to the proposed terms. I would add a customer communication tool and a customer interaction history, with a human review step before external messages are sent. Customer Service could then manage the interaction through completion rather than stopping at a draft.

These limitations also show why I wanted to distinguish administrative resolution from operational resolution. Completing the internal process doesn't necessarily mean the underlying customer problem has been solved.

### Final thoughts

The exercise reinforced my belief that human oversight should be designed into a system rather than added as a final precaution. None of the agents could independently execute a payment or resolve a ticket. They could investigate, make recommendations, and prepare requests, but certain decisions remained with a person.

I also came away thinking more carefully about how organizations define completion. Paying the supplier invoice didn't mean the customer had received the shirt, and approving a discount didn't mean the club had accepted the offer. A system can appear successful according to its metrics while leaving meaningful work unfinished. That seems especially relevant in organizations where performance is measured by completed tickets, closed cases, or turnaround times.

If I were developing this system further, I would focus on improving how agents interpret their responsibilities and evaluate their own outputs. I would want Customer Service responses checked for confidentiality and appropriateness before they were presented for approval. I would also want agents to distinguish between missing information that genuinely prevents a decision and missing information they are responsible for developing themselves.

Overall, the project changed how I think about multi-agent systems. I initially approached the agents as specialists that could divide work according to their functions. By the end, I was thinking about them much more like a management team. Having the right expertise represented wasn't enough. The system also needed clear authority, effective delegation, shared context, accountability, and a reliable way to recognize its own limitations.

The most important lesson for me was that **automating work and improving decision-making are not interchangeable**. AI can make a process faster and more efficient, but whether that process produces a good outcome still depends on how the system is designed, what behavior it rewards, and where human judgment remains involved.

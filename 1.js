// Get all emails from Outlook
const items = $input.all();

console.log(`📧 Total emails retrieved: ${items.length}`);

// ============================================
// PROCESS ALL EMAILS AUTOMATICALLY
// No manual changes needed
// ============================================

// Prepare all emails for API
const emails = items.map(i => i.json);

// Extract user ID from first email
const userId = items[0]?.json?.from?.emailAddress?.address || 
               items[0]?.json?.sender?.emailAddress?.address || 
               "Lars.Kiebula@tu-steuer.de";

console.log(`✅ Preparing ${emails.length} emails for processing`);
console.log(`👤 User ID: ${userId}`);

return [{
  json: {
    emails,
    user_id: userId
  }
}];
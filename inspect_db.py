from circulation.models import BorrowingTransaction, BookCopy
from catalog.models import Book

print("Checking copy MSICT/000094:")
try:
    copy = BookCopy.objects.get(accession_no='MSICT/000094')
    print(f"Copy: {copy.accession_no}, Status: {copy.status}")
    txs = BorrowingTransaction.objects.filter(copy=copy).order_by('-borrow_date')
    for tx in txs:
         print(f"  TX ID: {tx.id}, Status: {tx.status}, User: {tx.user.username}")
except Exception as e:
    print(e)
